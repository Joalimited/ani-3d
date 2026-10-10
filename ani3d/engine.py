"""The playback/search engine used by ani-3d: scraping, mpv control (JSON IPC) and the watch history. Cross-platform."""
import asyncio
import json
import os
import re
import sys
import tempfile
import time

from . import mpvlink, paths
from . import multisrc
from .core import (MANGA_SITE, backend, db_connect, db_log, db_watched, fetch_poster, find_manga,  # noqa: F401
                   home_data, related_content, resume_advance, resume_save, total_set)

SPEEDS = [0.75, 1.0, 1.25, 1.5, 2.0]


class Engine:
    def __init__(self):
        self.anime = None
        self.episodes = []
        self.mode = "sub"
        self.autonext = True
        self.cur_ep = None
        self.proc = None
        self.link = None
        self.token = 0
        self.eof = False
        self.state = {}
        self.sock = paths.ipc_name()
        self.last_emit = 0.0
        self.flush_pending = False
        self.autofs = False  # start every episode in fullscreen
        self.autoskip = {"intro": False, "outro": False}  # skip openings / credits automatically in every episode
        self._skipped = set()  # (episode, kind) already auto-skipped, so seeking back works
        self.skip = {}  # {"intro": (start, end), "outro": (start, end)} from the stream config, when it has one
        self.poster = ""
        self.source = ""
        self._resume_at = 0.0  # last time the watch position was written to the database

    # ----- io -----
    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def snapshot(self):
        s = self.state
        return {
            "playing": self.proc is not None, "anime": self.anime and {"id": self.anime[0], "title": self.anime[1]},
            "episode": self.cur_ep, "mode": self.mode, "autonext": self.autonext,
            "pos": s.get("time-pos") or 0, "duration": s.get("duration") or 0, "paused": bool(s.get("pause")),
            "volume": s.get("volume", 100), "muted": bool(s.get("mute")), "speed": s.get("speed", 1.0),
            "skip": self.skip_ranges(), "source": getattr(self, "source", ""), "autofs": self.autofs, "autoskip": dict(self.autoskip),
        }

    def skip_ranges(self):
        """Intro / outro ranges: the stream's own timestamps, else mpv chapters called OP/ED, else None (the buttons then use fixed jumps)."""
        found = dict(self.skip)
        for ch in self.state.get("chapter-list") or []:
            title = str(ch.get("title", "")).lower()
            kind = "intro" if re.search(r"\b(op|opening|intro|prologue)\b", title) else "outro" if re.search(r"\b(ed|ending|outro|credits?|epilogue)\b", title) else None
            if kind and kind not in found:
                idx = (self.state.get("chapter-list") or []).index(ch)
                nxt = (self.state.get("chapter-list") or [])[idx + 1:idx + 2]
                end = nxt[0]["time"] if nxt else (self.state.get("duration") or ch["time"])
                found[kind] = (float(ch["time"]), float(end))
        return {k: list(v) for k, v in found.items()}

    def emit(self, force=False):
        """Send the player state. Rapid updates are throttled, but the last one is always flushed."""
        now = time.monotonic()
        wait = 0.4 - (now - self.last_emit)
        if force or wait <= 0:
            self.last_emit = now
            self.send({"event": "player", "state": self.snapshot()})
        elif not self.flush_pending:
            self.flush_pending = True
            asyncio.get_running_loop().call_later(wait, self._flush)

    def _flush(self):
        self.flush_pending = False
        self.emit(force=True)

    # ----- commands -----
    async def handle(self, cmd, a):
        if cmd == "search":
            out = await backend("search", a["q"])
            rows = [(l.split("\t") + [""])[:3] for l in out.splitlines() if "\t" in l]
            for i, t, _ in rows[:4]:  # warm the cache so clicking one of the top results is instant
                asyncio.create_task(self.prefetch(i, t))
            return [{"id": i, "title": t, "poster": p} for i, t, p in rows]
        if cmd == "episodes":
            aid = a["id"]
            if aid.startswith("q:"):  # a recommendation: only a title so far, find the show on the sites
                aid = await asyncio.to_thread(multisrc.resolve, a["title"])
            out = await backend("episodes", aid, a.get("title", ""))
            eps = out.split()
            total_set(aid, len(eps))
            self.anime, self.episodes = (aid, a["title"]), eps
            return {"id": aid, "episodes": eps, "watched": sorted(db_watched(aid, a["title"]))}
        if cmd == "home":
            return await home_data()
        if cmd == "info":
            found = await find_manga(a["title"])
            return {"manga": [{"id": i, "title": n, "chapters": c, "url": f"{MANGA_SITE}/manga/{i}"} for i, n, c in found]}
        if cmd == "blurb":
            from .core import media_blurb  # noqa: PLC0415
            return await media_blurb(a["title"], a.get("kind", "anime"))
        if cmd == "related":
            return await related_content(a["title"])
        if cmd == "edits":
            from .core import fan_edits  # noqa: PLC0415
            return await fan_edits(a["title"])
        if cmd == "history":
            with db_connect() as con:
                rows = con.execute(
                    "SELECT COALESCE(anime_id,''), anime_name, group_concat(DISTINCT episode), max(timestamp) "
                    "FROM history GROUP BY COALESCE(anime_id, anime_name) ORDER BY max(timestamp) DESC LIMIT 100").fetchall()
            return [{"id": r[0], "title": r[1], "episodes": (r[2] or "").split(","), "last": r[3]} for r in rows]
        if cmd == "state":
            return self.snapshot()
        if cmd == "play":
            if a.get("mode"):
                self.mode = a["mode"]
            self.poster = a.get("poster") or self.poster
            if a.get("id") and (not self.anime or self.anime[0] != a["id"]):
                self.anime = (a["id"], a["title"])
                self.episodes = a.get("episodes") or self.episodes
            await self.play(str(a["ep"]), a.get("start", 0))
            return self.snapshot()
        if cmd == "control":
            return await self.control(a["action"], a.get("value"))
        raise ValueError(f"unknown command: {cmd}")

    async def prefetch(self, aid, title):
        try:
            await backend("episodes", aid)
            await find_manga(title)
        except Exception:
            pass

    async def control(self, action, v):
        if action == "pause":
            await self.mpv("cycle", "pause")
        elif action == "seek":
            await self.mpv("seek", v, "relative")
        elif action == "seekpct":
            await self.mpv("seek", v, "absolute-percent")
        elif action == "volume":
            await self.mpv("set_property", "volume", v)
        elif action == "mute":
            await self.mpv("cycle", "mute")
        elif action == "autoskip":
            self.autoskip = {"intro": bool((v or {}).get("intro")), "outro": bool((v or {}).get("outro"))}
            self._skipped.clear()
        elif action == "autofs":
            self.autofs = bool(v)
            if self.autofs and self.proc:
                await self.mpv("set_property", "fullscreen", True)
        elif action == "fullscreen":
            await self.mpv("cycle", "fullscreen")
        elif action == "subs":
            await self.mpv("cycle", "sub-visibility")
        elif action == "speed":
            await self.mpv("set_property", "speed", v)
        elif action == "autonext":
            self.autonext = bool(v)
        elif action == "stop":
            self.token += 1
            await self.kill()
            self.state = {}
            self.cur_ep = None
        elif action in ("next", "prev"):
            if self.cur_ep in self.episodes:
                i = self.episodes.index(self.cur_ep) + (1 if action == "next" else -1)
                if 0 <= i < len(self.episodes):
                    await self.play(self.episodes[i])
        elif action == "skip_intro":
            rng = self.skip_ranges().get("intro")
            pos = self.state.get("time-pos") or 0
            if rng and pos < rng[1] - 1:
                await self.mpv("seek", max(rng[1], pos), "absolute")
            else:
                await self.mpv("seek", 85, "relative")  # a typical opening is ~90 s long
        elif action == "skip_outro":
            rng = self.skip_ranges().get("outro")
            pos = self.state.get("time-pos") or 0
            dur = self.state.get("duration") or 0
            if rng and pos < rng[0] - 1:
                await self.mpv("seek", rng[0], "absolute")  # jump to where the credits start
            elif rng and pos < rng[1] - 1 and rng[1] < dur - 3:
                await self.mpv("seek", rng[1], "absolute")  # past the credits (there is a preview/scene after them)
            elif self.cur_ep in self.episodes and self.episodes.index(self.cur_ep) + 1 < len(self.episodes):
                await self.play(self.episodes[self.episodes.index(self.cur_ep) + 1])  # no timestamps: the next episode
            elif dur:
                await self.mpv("seek", max(dur - 2, 0), "absolute")
        elif action == "mode":
            self.mode = v or ("dub" if self.mode == "sub" else "sub")
            if self.proc and self.cur_ep:
                await self.play(self.cur_ep, self.state.get("time-pos") or 0)
        else:
            raise ValueError(f"unknown control: {action}")
        self.emit(force=True)
        return self.snapshot()

    # ----- playback -----
    async def play(self, ep, start=0):
        aid, title = self.anime
        self.token += 1
        token = self.token
        await self.kill()
        out = await backend("link", aid, ep, self.mode, title)
        if token != self.token:
            return
        video, refr, sub, skip, self.source = (out.split("\n") + ["", "", "", "", ""])[:5]
        try:
            self.skip = {k: tuple(v) for k, v in json.loads(skip or "{}").items()}
        except ValueError:
            self.skip = {}
        mpv_path = await asyncio.to_thread(paths.ensure_mpv)  # on Windows the first run unpacks the bundled mpv
        args = [mpv_path, "--no-terminal", f"--input-ipc-server={self.sock}", f"--referrer={refr}",
                f"--force-media-title={title} Episode {ep}", "--keep-open=no"]
        if "m3u8" in video:  # some hosts serve playlists under odd names ("...?t.m3u8"), which ffmpeg won't sniff as HLS
            args += ["--demuxer-lavf-format=hls", "--demuxer-lavf-o=allowed_extensions=ALL,allowed_segment_extensions=ALL,extension_picky=0"]
        if self.autofs:
            args.append("--fullscreen")
        args += os.environ.get("ANI3D_MPV_ARGS", "").split()  # extra mpv options (used by the headless self-tests)
        if sub:
            args.append(f"--sub-file={sub}")
        if start:
            args.append(f"--start={int(start)}")
        args.append(video)
        if not paths.WINDOWS:
            try:
                os.unlink(self.sock)
            except OSError:
                pass
        self.eof, self.state, self.cur_ep = False, {}, ep
        self._skipped = set()
        kw = {"creationflags": 0x08000000} if paths.WINDOWS else {}  # CREATE_NO_WINDOW: no console flash next to the player
        self.proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **kw)
        db_log(aid, title, ep)
        self.send({"event": "watched", "anime_id": aid, "episodes": sorted(db_watched(aid, title))})
        self.emit(force=True)
        asyncio.create_task(self.watch(self.proc, token))

    async def watch(self, proc, token):
        link = await mpvlink.connect(self.sock, proc)
        self.link = link
        if link:
            for i, p in enumerate(["time-pos", "duration", "pause", "volume", "mute", "speed", "chapter-list"], 1):
                await self.mpv("observe_property", i, p)
            try:
                while line := await link.readline():
                    try:
                        m = json.loads(line)
                    except ValueError:
                        continue
                    if m.get("event") == "property-change":
                        self.state[m["name"]] = m.get("data")
                        self.emit()
                        if m["name"] == "time-pos" and time.time() - self._resume_at > 5 and token == self.token:
                            self._resume_at = time.time()
                            self.save_resume()
                        if m["name"] in ("time-pos", "chapter-list") and token == self.token:
                            await self.auto_skip()
                    elif m.get("event") == "end-file" and m.get("reason") == "eof":
                        self.eof = True
                        if token == self.token:
                            self.save_resume(finished=True)
            except (ConnectionError, OSError):
                pass
        await proc.wait()
        if token != self.token:
            return
        self.proc, self.link, self.state = None, None, {}
        self.emit(force=True)
        if self.eof and self.autonext and self.cur_ep in self.episodes:
            i = self.episodes.index(self.cur_ep)
            if i + 1 < len(self.episodes):
                try:
                    await self.play(self.episodes[i + 1])
                except Exception as e:
                    self.send({"event": "error", "message": str(e)})

    async def auto_skip(self):
        """Honour the intro / credits auto-skip switches for the episode that is playing (once each)."""
        pos = self.state.get("time-pos")
        if pos is None or not (self.autoskip["intro"] or self.autoskip["outro"]):
            return
        rng = self.skip_ranges()
        dur = self.state.get("duration") or 0
        ep = self.cur_ep
        intro = rng.get("intro")
        if self.autoskip["intro"] and (ep, "intro") not in self._skipped:
            if intro and intro[0] - 1 <= pos < intro[1] - 1:
                self._skipped.add((ep, "intro"))
                await self.mpv("seek", intro[1], "absolute")
                return
            if not intro and 2 <= pos < 30:  # no timestamps: jump a typical opening length once
                self._skipped.add((ep, "intro"))
                await self.mpv("seek", 85, "relative")
                return
        outro = rng.get("outro")
        if self.autoskip["outro"] and outro and (ep, "outro") not in self._skipped and outro[0] - 0.5 <= pos < outro[1]:
            self._skipped.add((ep, "outro"))
            if outro[1] >= dur - 5 and ep in self.episodes and self.episodes.index(ep) + 1 < len(self.episodes) and self.autonext:
                asyncio.create_task(self.play(self.episodes[self.episodes.index(ep) + 1]))  # credits run to the end: next episode
            elif outro[1] < dur - 5:
                await self.mpv("seek", outro[1], "absolute")
            else:
                await self.mpv("seek", max(dur - 1, 0), "absolute")

    def save_resume(self, finished=False):
        """Write the playing episode's position to the resume table; a (nearly) finished episode moves on to the next one."""
        if not (self.anime and self.cur_ep):
            return
        pos, dur = self.state.get("time-pos") or 0, self.state.get("duration") or 0
        aid, title = self.anime
        if finished or (dur and pos / dur > 0.92):
            nxt = None
            if self.cur_ep in self.episodes:
                i = self.episodes.index(self.cur_ep)
                nxt = self.episodes[i + 1] if i + 1 < len(self.episodes) else None
            resume_advance(aid, title, nxt)
        elif pos > 5:
            resume_save(aid, title, self.cur_ep, pos, dur, self.poster)

    async def kill(self):
        if self.proc:
            self.save_resume()
        proc, self.proc, self.link = self.proc, None, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                proc.kill()

    async def mpv(self, *cmd):
        if self.link:
            try:
                await self.link.send(cmd)
            except (ConnectionError, OSError):
                pass


