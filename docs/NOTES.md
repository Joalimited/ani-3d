# ani-3d developer notes

FSN (Jurassic Park "File System Navigator") style 3D front-end for ani-tui. Run `ani-3d`.

wgpu on the Vulkan backend (`WGPU_BACKEND_TYPE=Vulkan`, discrete GPU preferred) draws the world: a root pedestal wired to one
pedestal per anime (poster on top), and a stadium of episode blocks. It runs the ani-tui engine in-process, so playback,
watch history (Watch-history.db) and the caches are shared with ani-tui / ani-app.

- `ani3d/renderer.py` Vulkan pipelines (floor, instanced neon boxes, textured quads, 4x MSAA)
- `ani3d/scene.py` layout, camera, picking · `ani3d/app.py` input, HUD, engine glue · `ani3d/text.py` text textures
- Headless render for testing: `python run.py --snapshot out.png "frieren" 0 1600x896`

## Themes, arcade, library
- `t` / THEME cycles Classic FSN, Jurassic Park, Halloween, Matrix, Retro Arcade and Old VCR (saved in `~/.config/ani-3d/settings.json`; `ANI3D_THEME=vcr` overrides).
  The VCR theme adds scanlines, a rolling tracking band, tape noise, a PLAY/STOP + timecode OSD and floating cassettes (`ani3d/effects.py`, `App.vcr_overlay`).
- Halloween is a haunted graveyard like the Jurassic herd (`ani3d/haunt.py`): ghosts (BOO), skeletons (fall apart and re-assemble), zombies and cats (drop candy
  with a click on the ground), a witch on a broom and spiders on silk threads; click one for an info card, `v` follows it.
- `g` / ARCADE (keys 1-7): Snake, Breakout, Poster Quiz, Barrel Climb, Anime Trivia, Data Maze, Dino Galaga. `ani3d/games.py`, `maze.py`, `galaga.py`
  - Barrel Climb: five different stages (more shelves, faster barrels, fireballs), then it laps; hammers (9 s) smash barrels and fireballs.
  - Data Maze: an FSN-style neon maze; a clue names an item from an anime (from your own list when it can) and there are decoys.
  - Dino Galaga: pick a dinosaur ship (Rex / Raptor / Triceratops / Pteranodon); every wave ends with an anime-character boss.
- `l` / LIBRARY: a bookshelf built from the watch history; walk with A/D, climb with W/S, Enter pulls a book out, C walks to your next-up book. `ani3d/library.py`
  Drag a book with the mouse to another shelf; the placement is stored in the watch database (`shelf_override`).
- Manga shelf: the librarian (click her or press `/`) searches MangaDex; `J` switches the shelf titles between English and Japanese (romaji), `P` (or the PAGES
  button) between right-to-left (default) and left-to-right. OPEN IN DOCUMENT READER writes a chapter as a PDF (`~/Documents/ani-3d manga/`) and opens it with
  the system's default reader. Titles MangaDex has no hosted chapters for get a MangaFire button (opens its search in the browser).
- TROPHIES (`ani3d/advance.py`): advancements generated from what you watch and read (a ladder per anime, global ones, manga and arcade ones).
- `h` / HISTORY works from anywhere (library, games, open books) and groups your history by how recently you watched.
- Search results are laid out in labelled sections (main series / seasons and sequels / movies / OVA-ONA-specials) on platforms wired to the root.
- The search bar suggests titles as you type (your history first, then the source's results; up/down, Tab completes, Enter searches).
- Media bar: SUB/DUB, SKIP INTRO (`i`) and SKIP CREDITS (`o`). hianime streams carry real intro/outro timestamps; otherwise mpv chapters are used, then +85 s / next episode.
- `e` / the info panel lists fan edits (AMVs) found on YouTube.

## Sources
hianime first (`ani3d/scrape.py`). When it has no match, or cannot stream an episode, miruro.to is used (`mi_search` / `mi_link`: its catalog API, XOR+gzip encoded,
returns HLS streams; each candidate is probed before being handed to mpv). MangaDex hosts readable chapters, but often only part of a series: when MangaPill, MangaKatana or
MangaRead (`ani3d/mangasrc.py`) have clearly more chapters, `core.full_chapters` switches the book to that site, and the librarian searches all of them (one entry per series, most chapters wins). MangaFire is a link-out only.

## The book (book.py) and the manga shelf
- The open book leans back on a lectern (instances have a pitch), pages curve into the gutter, stacks are layered curved strips,
  the turning leaf is a chain of strips with a trailing/settling curl and the page text is mapped across them.
- Manga use the same engine mirrored when read right to left (the default): spine on the right, left arrow = next page.
- `M` (or MANGA) opens the manga shelf: READING / MANGA OF YOUR ANIME / POPULAR / FINISHED. Chapters come from the MangaDex public API
  (only series with hosted chapters appear; licensed series such as Frieren have none). Reading progress is saved in `manga_read`.
- Keys in an open manga: left/right (A/D) turn, `[` `]` previous/next chapter, `O` chapter list, click a chapter to read it.

## Reader controls (open book)
- Zoom: mouse wheel, `+`/`-`, or the ZOOM buttons; `Z` fits one page (cycles first page / second page / whole spread); drag pans; `0` resets.
- Manga read right to left by default (spine on the right, left arrow = next page). `G` (or the READ / PAGES buttons) switches to left-to-right; saved as `manga_rtl_v2` in `~/.config/ani-3d/settings.json`.
- `U` hides all buttons and labels (a faint "SHOW UI (U)" chip stays in the corner). While hidden and a book is open, click the left/right
  edge of the screen to turn pages. The mouse wheel zooms the open book (and the camera when no book is open).

## Jurassic Park theme: the herd
`ani3d/dinos.py` builds eight articulated species from boxes (jointed legs, swaying tails, S-curved necks, hinged jaws, three-part wings).
Boxes can roll in their own frame (`rollz`/`rollx`), which is what lets limbs swing about a hip. Click a dinosaur to make it roar (camera shake,
shockwave, info card), click the ground to drop food (the nearest matching animal walks over and eats), `V` follows one. Small and prey animals flee a roaring T-Rex.
Loading: page art and posters are decoded/drawn on worker threads and uploaded a couple per frame; `ani-3d --snapshot` and `audit.py`-style checks live in the scratch notes.

## Windows build
`./build_windows.sh` builds `dist/ani-3d.exe` (single file, PyInstaller `--onefile --noupx`) inside a Podman container that runs Windows Python 3.12 under Wine
(image `tobix/pywine:3.12`). It needs `~/ani-3d-build/mpv.zip` (zip of a Windows mpv build). `MODE=console ./build_windows.sh` makes a debug build that prints errors.
Cross-platform pieces: `ani3d/scrape.py` (pure-Python hianime scraper, replaces the shell script), `ani3d/paths.py` (per-OS folders, finding/unpacking mpv),
`ani3d/mpvlink.py` (mpv IPC: Unix socket or an overlapped named pipe), pinned deps: numpy 1.26.4, wgpu 0.32.0, rendercanvas 2.7.2, glfw 2.10.2.
`ani-3d.exe --check [file]` runs a no-GPU self check (used to verify the build under Wine).
