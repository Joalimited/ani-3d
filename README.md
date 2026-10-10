# ani-3d

A 3D anime and manga browser in the style of the "File System Navigator" from *Jurassic Park*. Search for a show, fly over
its posters on glowing pedestals, pick an episode from a field of blocks and it plays in mpv. Your shows also live on a
walkable bookshelf, manga open as real books you can flip through, and there are themes, mini-games and trophies on top.

Runs on Linux and Windows with any GPU that supports Vulkan or Direct3D 12.

## Getting started

### Linux (AppImage)

1. Install **mpv** (it plays the episodes) and make sure your GPU has a Vulkan driver (Mesa on AMD/Intel, the proprietary
   driver on NVIDIA):

   ```sh
   sudo dnf install mpv        # Fedora
   sudo apt install mpv        # Debian / Ubuntu
   ```

2. Build the AppImage (see [Building](#building)) or use one you already have, then run it:

   ```sh
   chmod +x ani-3d-x86_64.AppImage
   ./ani-3d-x86_64.AppImage
   ```

### Windows (exe)

`ani-3d.exe` is a single file with mpv bundled inside - just double-click it. It needs Windows 10 or newer and a graphics
driver with Direct3D 12 or Vulkan.

### From source (Linux)

Install **mpv**, then clone and run:

```sh
git clone https://github.com/Joalimited/ani-3d.git
cd ani-3d
./ani-3d
```

The first run sets itself up (about a minute): it makes a Python 3.12 environment in `.venv` and installs the packages.
If Python 3.12 isn't installed, it uses [uv](https://github.com/astral-sh/uv) to download it. After that `./ani-3d`
starts straight away.

### From source (Windows / manual)

You need **Python 3.12** and **mpv** on your `PATH`.

```sh
python3.12 -m venv .venv
.venv\Scripts\activate            # Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Not sure everything is set up? `./ani-3d --check` (or `python run.py --check`) runs a self-check (graphics adapter, sources, mpv, fonts) and
prints what works and what doesn't.

## First steps

- The app opens on **HOME**: shows to continue watching, recommendations and what's popular. Click a poster to open it,
  then click an episode block to play it. Continue-watching shows resume where you stopped.
- Press **/** to search. Hover a poster to see its description.
- **L** opens the anime library (a bookshelf of what you watch), **M** the manga library, **G** the arcade, **T** cycles
  the theme, **H** shows your history, **U** hides the interface.

| Where | Keys |
| --- | --- |
| World | drag = orbit, right-drag = pan, wheel = zoom, `Esc` = back, `space` = pause, arrows = seek / volume, `n` / `p` = next / previous episode, `d` = sub / dub |
| Library | `A`/`D` walk, `W`/`S` climb, `Enter` open a book, `F` star (anime) or add to Going To Read (manga), `X` remove, drag books between shelves |
| Open book | arrows or `A`/`D` turn pages, `[` `]` previous / next chapter, `O` chapter list, wheel or `+`/`-` zoom, `Z` fit page, `G` reading direction |

## Themes

Classic FSN, Jurassic Park (a herd of dinosaurs you can feed and follow), Enchanted Forest (frogs, ladybugs, beetles and
butterflies), Sakura Garden, Halloween (a haunted graveyard), Matrix, Retro Arcade and Old VCR. Press **T** to switch;
the choice is remembered.

## Where your data lives

| What | Linux | Windows |
| --- | --- | --- |
| Watch history, reading progress, shelves | `~/Watch-history.db` | `%USERPROFILE%\Watch-history.db` |
| Settings (theme, reader options) | `~/.config/ani-3d/settings.json` | `%APPDATA%\ani-3d\settings.json` |
| Cache (posters, lookups) | `~/.cache/ani-tui/` | `%LOCALAPPDATA%\ani-3d\cache\` |
| Exported manga chapters (PDF) | `~/Documents/ani-3d manga/` | `Documents\ani-3d manga\` |

Set `ANI_CLI_WATCH_DB` to keep the history database somewhere else. Nothing is uploaded anywhere.

## Building

- **Linux AppImage:** `./build_appimage.sh` builds `dist/ani-3d-x86_64.AppImage` with PyInstaller from a Python 3.12
  virtual environment in `~/ani-3d-build/venv312` (the script prints how to create it).
- **Windows exe:** `./build_windows.sh` builds `dist/ani-3d.exe` inside a Podman (or Docker) container that runs
  Windows Python under Wine. It needs `~/ani-3d-build/mpv.zip`, a zip of a Windows mpv build, which gets bundled into the
  exe. `MODE=console ./build_windows.sh` makes a debug build that shows errors.
- `test_builds.sh` is the author's own post-build check (a Windows VM, Wine and the AppImage); adapt it to your setup.

Developer notes on how everything fits together are in [`docs/NOTES.md`](docs/NOTES.md).

## Thanks

- **[ani-cli](https://github.com/pystardust/ani-cli)** - a huge thank you to the ani-cli project and its contributors.
  ani-3d started as a front-end for an ani-cli based setup, and its scraper (`ani3d/scrape.py`) is a Python port of
  ani-cli style scraping so it can run on Windows too. Without ani-cli this project would not exist.
- [mpv](https://mpv.io/) for playback.
- [MangaDex](https://mangadex.org/), [AniList](https://anilist.co/) and [Jikan](https://jikan.moe/) (MyAnimeList) for
  their public APIs.
- [wgpu-py](https://github.com/pygfx/wgpu-py), [rendercanvas](https://github.com/pygfx/rendercanvas) and
  [glfw](https://www.glfw.org/) for the graphics.
- [Noto Sans Mono](https://fonts.google.com/noto) (SIL Open Font License, see `ani3d/fonts/NOTO-LICENSE.txt`).

## Disclaimer

ani-3d does not host any content. It finds streams and chapters on third-party websites, the same way ani-cli does. Use
it in line with the laws where you live and the terms of the sites involved.

## License

GPL-3.0, the same license as ani-cli. See [LICENSE](LICENSE).
