#!/bin/sh
# Run after every build: tests dist/ani-3d.exe in the Windows 10 VM (container winvm, software D3D12) and in Wine, and the AppImage natively.
HERE="$(cd "$(dirname "$0")" && pwd)"; VM="$HOME/ani-3d-vm"
podman start winvm >/dev/null 2>&1   # then wait for the desktop + the job runner (see memory: windows-vm-testing)
cp "$HERE/dist/ani-3d.exe" "$VM/shared/ani-3d.exe"
cp "$VM/test-job.ps1" "$VM/shared/jobs/test-$(date +%s).ps1"
echo "VM job queued; results land in $VM/shared/jobs/*.out (UTF-16: iconv -f utf-16 -t utf-8)"
echo "--- Wine ---"
podman run --rm --security-opt label=disable -v "$HERE/dist:/dist:ro" tobix/pywine:3.12 sh -c 'cp /dist/ani-3d.exe /tmp/a.exe; cd /tmp; timeout 200 wine a.exe --check /tmp/c.txt >/dev/null 2>&1; cat /tmp/c.txt'
echo "--- AppImage ---"
"$HERE/dist/ani-3d-x86_64.AppImage" --appimage-extract-and-run --check /dev/stdout 2>/dev/null | tail -4
