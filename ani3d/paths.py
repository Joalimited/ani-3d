"""Where things live on each OS, bundled resources, and finding (or unpacking) mpv."""
import os
import shutil
import sys
import zipfile

WINDOWS = sys.platform == "win32"


def _home():
    return os.path.expanduser("~")


def cache_dir():
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA", _home()), "ani-3d", "cache")
    return os.path.join(_home(), ".cache", "ani-tui")


def config_dir():
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA", _home()), "ani-3d")
    return os.path.join(_home(), ".config", "ani-3d")


def data_dir():
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA", _home()), "ani-3d")
    return os.path.join(_home(), ".local", "share", "ani-3d")


def watch_db():
    return os.environ.get("ANI_CLI_WATCH_DB", os.path.join(_home(), "Watch-history.db"))


def resource(*parts):
    """Path of a bundled data file (works from source and from a PyInstaller exe)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def ipc_name(pid=None):
    pid = pid or os.getpid()
    return rf"\\.\pipe\ani3d-mpv-{pid}" if WINDOWS else os.path.join(os.environ.get("TMPDIR", "/tmp"), f"ani3d-mpv-{pid}.sock")


def find_mpv():
    """mpv on PATH, a copy we unpacked earlier, or None."""
    exe = "mpv.exe" if WINDOWS else "mpv"
    found = shutil.which("mpv")
    if found:
        return found
    local = os.path.join(data_dir(), "mpv", exe)
    return local if os.path.exists(local) else None


def ensure_mpv():
    """Find mpv; on Windows unpack the bundled copy the first time. Raises with a helpful message if there is none."""
    path = find_mpv()
    bundle = resource("mpv.zip")
    if path:
        # A copy unpacked by an older build lacks vulkan-1.dll (clean Windows has none, and mpv.exe imports it).
        local = os.path.join(data_dir(), "mpv")
        stale = WINDOWS and os.path.dirname(path) == local and not os.path.exists(os.path.join(local, "vulkan-1.dll"))
        if not (stale and os.path.exists(bundle)):
            return path
    if os.path.exists(bundle):
        target = os.path.join(data_dir(), "mpv")
        os.makedirs(target, exist_ok=True)
        with zipfile.ZipFile(bundle) as z:
            z.extractall(target)
        path = find_mpv()
        if path:
            return path
    raise RuntimeError("mpv was not found. Install it (Windows: winget install mpv, Linux: your package manager) and try again.")


def open_file(path):
    """Open a file with the system's default program (PDF reader, image viewer, ...)."""
    import subprocess

    if WINDOWS:
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def documents_dir():
    """Where exported manga chapters (PDF) are written."""
    docs = os.path.join(_home(), "Documents")
    base = docs if os.path.isdir(docs) else data_dir()
    return os.path.join(base, "ani-3d manga")
