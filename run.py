#!/usr/bin/env python
"""ani-3d entry point (also the PyInstaller entry for the Windows exe)."""
import multiprocessing
import os
import sys

if sys.platform.startswith("linux"):
    os.environ.setdefault("WGPU_BACKEND_TYPE", "Vulkan")  # on Linux wgpu runs on Vulkan; Windows picks Direct3D 12 or Vulkan itself
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check(out_path=None):
    """No-GPU self check: imports, fonts, scraper, database and mpv lookup. Used to verify a build (exit code 0 = ok)."""
    import tempfile

    log = open(out_path, "w", encoding="utf-8") if out_path else None

    def say(msg):
        print(msg, flush=True)
        if log:
            log.write(msg + "\n")
            log.flush()

    os.environ.setdefault("ANI_CLI_WATCH_DB", os.path.join(tempfile.mkdtemp(), "check.db"))
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            say(f"[ ok ] {name}: {fn()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            say(f"[FAIL] {name}: {type(e).__name__}: {e}")

    from ani3d import core, paths, scrape, text, themes

    step("platform", lambda: sys.platform)
    step("font", lambda: text.find_font())
    step("settings dir", lambda: paths.config_dir())
    step("watch db", lambda: (core.db_connect().execute("select count(*) from history").fetchone(), core.WATCH_DB)[1])
    step("wgpu", lambda: __import__("wgpu").__version__)
    step("glfw", lambda: __import__("glfw").__version__)
    step("rendercanvas", lambda: __import__("rendercanvas").__version__)
    step("numpy/Pillow", lambda: (__import__("numpy").__version__, __import__("PIL").__version__))
    step("scraper: search", lambda: f"{len(scrape.search('frieren'))} results")
    step("scraper: episodes", lambda: f"{len(scrape.episodes('frieren-beyond-journeys-end-481'))} episodes")
    step("scraper: stream link", lambda: scrape.link("frieren-beyond-journeys-end-481", "1", "sub")[0][:60] + "...")
    step("miruro fallback: search", lambda: f"{len(scrape.mi_search('frieren'))} results")
    step("miruro fallback: stream link", lambda: scrape.mi_link(scrape.mi_search("frieren")[0][0], "1", "sub")[0][:60] + "...")
    step("manga api", lambda: f"{len(__import__('asyncio').run(core.md_popular(5)))} popular titles")
    step("mpv", lambda: paths.find_mpv() or ("bundled copy (unpacks on first play)" if os.path.exists(paths.resource("mpv.zip")) else "NOT FOUND"))
    def mpv_run():
        import subprocess

        path = paths.ensure_mpv()  # unpacks the bundled copy on Windows the first time
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60).stdout.splitlines()
        return f"{path} -> {out[0] if out else '?'}"
    step("mpv unpack + run", mpv_run)
    step("themes", lambda: ", ".join(themes.ORDER))
    step("gpu adapter", lambda: (lambda a: f"{a.info.get('device')} ({a.info.get('backend_type')})" if a else "none found")(__import__("wgpu").gpu.request_adapter_sync(power_preference="high-performance")))
    say("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


def report_crash():
    """The Windows exe has no console, so show what went wrong in a dialog and keep a log."""
    import traceback

    from ani3d import paths

    text = traceback.format_exc()
    try:
        os.makedirs(paths.data_dir(), exist_ok=True)
        log = os.path.join(paths.data_dir(), "crash.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        log = "(could not write a log)"
    hint = ""
    if "adapter" in text.lower() or "wgpu" in text.lower():
        hint = "\n\nThis usually means the graphics driver is too old or missing Direct3D 12 / Vulkan support. Updating your GPU driver normally fixes it."
    msg = f"ani-3d hit a problem and had to close.{hint}\n\nDetails were saved to:\n{log}\n\n{text.strip().splitlines()[-1]}"
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, msg, "ani-3d", 0x10)
        except Exception:  # noqa: BLE001
            pass
    else:
        print(msg, file=sys.stderr)


def tee_to_log():
    """ANI3D_LOG=<file>: send everything the app prints (and any traceback) to a file. The Windows exe has no console."""
    path = os.environ.get("ANI3D_LOG")
    if not path:
        return
    f = open(path, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = f


if __name__ == "__main__":
    multiprocessing.freeze_support()
    tee_to_log()
    args = sys.argv[1:]
    if args and args[0] == "--check":
        sys.exit(check(args[1] if len(args) > 1 else None))
    try:
        from ani3d import app

        if args and args[0] == "--snapshot":
            # --snapshot out.png "query" [select_index] [WxH]
            out, query = args[1], args[2]
            select = int(args[3]) if len(args) > 3 and args[3] != "-" else None
            size = tuple(int(v) for v in args[4].split("x")) if len(args) > 4 else (1600, 896)
            app.run_snapshot(out, query, select, size)
        else:
            app.run_window()
    except Exception:  # noqa: BLE001
        report_crash()
        sys.exit(1)
