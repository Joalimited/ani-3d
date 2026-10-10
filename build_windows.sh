#!/bin/sh
# Builds dist/ani-3d.exe (a single-file Windows executable) from this source tree, inside a Podman/Docker container that
# runs Windows Python + PyInstaller under Wine. Needs: podman (or docker), ~/ani-3d-build/mpv.zip (a zipped Windows mpv build).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="${BUILD_DIR:-$HOME/ani-3d-build}"
ENGINE="${CONTAINER_ENGINE:-podman}"
MODE="${MODE:-windowed}"   # MODE=console builds a debug exe that prints errors
NAME="ani-3d"; [ "$MODE" = console ] && NAME="ani-3d-console"
IMAGE="docker.io/tobix/pywine:3.12"
[ -f "$BUILD/mpv.zip" ] || { echo "missing $BUILD/mpv.zip (zip of mpv.exe + d3dcompiler_43.dll + mpv/ from a Windows mpv build)"; exit 1; }

rm -rf "$BUILD/src" "$BUILD/out"; mkdir -p "$BUILD/src" "$BUILD/out"
cp "$HERE/run.py" "$BUILD/src/"
cp -r "$HERE/ani3d" "$BUILD/src/ani3d"
find "$BUILD/src" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$BUILD/mpv.zip" "$BUILD/src/mpv.zip"

# a small neon-cube icon so the exe is recognisable in Explorer
python3 - "$BUILD/src/icon.ico" <<'PY'
import sys, math
from PIL import Image, ImageDraw
S = 256
im = Image.new("RGBA", (S, S), (6, 10, 24, 255))
d = ImageDraw.Draw(im)
for i in range(0, S, 32):
    d.line([(i, S), (S // 2 + (i - S // 2) // 3, 150)], fill=(16, 60, 110, 255))
    d.line([(0, 150 + i // 2), (S, 150 + i // 2)], fill=(16, 60, 110, 255))
c = (S // 2, 120)
top = [(c[0], c[1] - 70), (c[0] + 70, c[1] - 30), (c[0], c[1] + 10), (c[0] - 70, c[1] - 30)]
left = [(c[0] - 70, c[1] - 30), (c[0], c[1] + 10), (c[0], c[1] + 90), (c[0] - 70, c[1] + 50)]
right = [(c[0] + 70, c[1] - 30), (c[0], c[1] + 10), (c[0], c[1] + 90), (c[0] + 70, c[1] + 50)]
d.polygon(top, fill=(40, 190, 255, 255)); d.polygon(left, fill=(20, 100, 190, 255)); d.polygon(right, fill=(255, 60, 200, 255))
for poly in (top, left, right):
    d.line(poly + [poly[0]], fill=(200, 250, 255, 255), width=4)
im.save(sys.argv[1], sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
PY

$ENGINE run --rm -e MODE=$MODE -e NAME=$NAME -v "$BUILD/src:/src:Z" -v "$BUILD/out:/out:Z" -w /src "$IMAGE" sh -c '
  set -e
  wine pip install --no-warn-script-location -q "wgpu==0.32.0" "rendercanvas==2.7.2" "glfw==2.10.2" "numpy==1.26.4" pillow httpx pyinstaller 2>&1 | tail -3
  wine pyinstaller --noconfirm --clean --onefile --noupx --$MODE --name $NAME --icon icon.ico \
      --collect-all wgpu --collect-all glfw --collect-data rendercanvas \
      --hidden-import rendercanvas.glfw --hidden-import rendercanvas.auto --hidden-import rendercanvas.asyncio --hidden-import rendercanvas.base \
      --hidden-import rendercanvas.core.coreutils --hidden-import rendercanvas.core.encoders --hidden-import rendercanvas.core.enums \
      --hidden-import rendercanvas.core.events --hidden-import rendercanvas.core.loop --hidden-import rendercanvas.core.scheduler --hidden-import rendercanvas.core.size \
      --hidden-import rendercanvas.contexts --hidden-import rendercanvas.contexts.basecontext --hidden-import rendercanvas.contexts.bitmapcontext \
      --hidden-import rendercanvas.contexts.wgpucontext --hidden-import rendercanvas.utils.asyncadapter --hidden-import rendercanvas.utils.asyncs \
      --hidden-import wgpu.backends.wgpu_native --hidden-import wgpu.backends.auto --hidden-import wgpu.backends.utils \
      --add-data "ani3d/fonts;fonts" --add-data "mpv.zip;." \
      --distpath /out --workpath /tmp/pyi-work --specpath /src run.py 2>&1 | tail -15
'
ls -la "$BUILD/out"
mkdir -p "$HERE/dist" && cp "$BUILD/out/$NAME.exe" "$HERE/dist/$NAME.exe" && echo "built: $HERE/dist/$NAME.exe"
