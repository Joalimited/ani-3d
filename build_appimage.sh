#!/bin/sh
# Builds dist/ani-3d-x86_64.AppImage: PyInstaller (onedir) -> AppDir -> appimagetool.
# Uses the Python 3.12 + pinned-dependency venv (~/ani-3d-build/venv312). The AppImage relies on the system's Vulkan driver and mpv.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="${BUILD_DIR:-$HOME/ani-3d-build}"
PY="$BUILD/venv312/bin/python"
[ -x "$PY" ] || { echo "missing $PY (create it: uv venv --python 3.12 $BUILD/venv312 && uv pip install --python $PY wgpu==0.32.0 rendercanvas==2.7.2 glfw==2.10.2 numpy==1.26.4 pillow httpx)"; exit 1; }
"$PY" -c "import PyInstaller" 2>/dev/null || uv pip install -q --python "$PY" pyinstaller

TOOL="$BUILD/appimagetool"
if [ ! -x "$TOOL" ]; then
  curl -L -s -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi

W="$BUILD/appimage-work"; rm -rf "$W"; mkdir -p "$W/src" "$W/AppDir/usr/bin"
cp "$HERE/run.py" "$W/src/"; cp -r "$HERE/ani3d" "$W/src/ani3d"; find "$W/src" -name __pycache__ -type d -prune -exec rm -rf {} +
cd "$W/src"
"$PY" -m PyInstaller --noconfirm --clean --onedir --noupx --name ani-3d \
  --collect-all wgpu --collect-all glfw --collect-data rendercanvas \
  --hidden-import rendercanvas.glfw --hidden-import rendercanvas.auto --hidden-import rendercanvas.asyncio --hidden-import rendercanvas.base \
  --hidden-import rendercanvas.core.coreutils --hidden-import rendercanvas.core.encoders --hidden-import rendercanvas.core.enums \
  --hidden-import rendercanvas.core.events --hidden-import rendercanvas.core.loop --hidden-import rendercanvas.core.scheduler --hidden-import rendercanvas.core.size \
  --hidden-import rendercanvas.contexts --hidden-import rendercanvas.contexts.basecontext --hidden-import rendercanvas.contexts.bitmapcontext \
  --hidden-import rendercanvas.contexts.wgpucontext --hidden-import rendercanvas.utils.asyncadapter --hidden-import rendercanvas.utils.asyncs \
  --hidden-import wgpu.backends.wgpu_native --hidden-import wgpu.backends.auto --hidden-import wgpu.backends.utils \
  --add-data "$W/src/ani3d/fonts:fonts" --distpath "$W/pyi-dist" --workpath "$W/pyi-work" --specpath "$W" run.py > "$W/pyinstaller.log" 2>&1 || { tail -20 "$W/pyinstaller.log"; exit 1; }

cp -r "$W/pyi-dist/ani-3d" "$W/AppDir/usr/bin/ani-3d"
cat > "$W/AppDir/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export WGPU_BACKEND_TYPE="${WGPU_BACKEND_TYPE:-Vulkan}"
command -v mpv >/dev/null 2>&1 || echo "ani-3d: mpv is not installed - install it (e.g. sudo dnf install mpv / sudo apt install mpv) to play episodes" >&2
exec "$HERE/usr/bin/ani-3d/ani-3d" "$@"
RUN
chmod +x "$W/AppDir/AppRun"
cat > "$W/AppDir/ani-3d.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=ani-3d
Comment=3D file-system-navigator style anime and manga browser
Exec=ani-3d
Icon=ani-3d
Categories=AudioVideo;Video;
Terminal=false
DESK
python3 - "$W/AppDir/ani-3d.png" <<'PY'
import sys
from PIL import Image, ImageDraw
S = 256; im = Image.new("RGBA", (S, S), (6, 10, 24, 255)); d = ImageDraw.Draw(im); c = (S // 2, 120)
top = [(c[0], c[1] - 70), (c[0] + 70, c[1] - 30), (c[0], c[1] + 10), (c[0] - 70, c[1] - 30)]
left = [(c[0] - 70, c[1] - 30), (c[0], c[1] + 10), (c[0], c[1] + 90), (c[0] - 70, c[1] + 50)]
right = [(c[0] + 70, c[1] - 30), (c[0], c[1] + 10), (c[0], c[1] + 90), (c[0] + 70, c[1] + 50)]
d.polygon(top, fill=(40, 190, 255, 255)); d.polygon(left, fill=(20, 100, 190, 255)); d.polygon(right, fill=(255, 60, 200, 255))
for poly in (top, left, right): d.line(poly + [poly[0]], fill=(200, 250, 255, 255), width=4)
im.save(sys.argv[1])
PY
mkdir -p "$HERE/dist"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$W/AppDir" "$HERE/dist/ani-3d-x86_64.AppImage" > "$W/appimagetool.log" 2>&1 || { tail -15 "$W/appimagetool.log"; exit 1; }
ls -la "$HERE/dist/ani-3d-x86_64.AppImage"
