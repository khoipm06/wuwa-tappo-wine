#!/usr/bin/env bash
# Universal setup script for Wuwa Tappo on Linux.
# Configures isolated prefix, patched Wine runtime, PE memory alignment, and C sidecars.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${REPO_DIR}/runtime/wine-runtime"

# 1. Determine prefix location
DEFAULT_PFX="/var/mnt/LData/tappo-prefix/pfx"
if [ ! -d "${DEFAULT_PFX}" ]; then
    DEFAULT_PFX="${HOME}/.local/share/wuwa-tappo/prefix"
fi
TAPPO_PREFIX="${WUWA_PREFIX:-${DEFAULT_PFX}}"
mkdir -p "${TAPPO_PREFIX}"

echo "[setup] Prefix directory: ${TAPPO_PREFIX}"

# 2. Build isolated Wine runtime if not already built
"${REPO_DIR}/runtime/build_runtime.sh"

WINE="${RUNTIME_DIR}/bin/wine"
WINESERVER="${RUNTIME_DIR}/bin/wineserver"
export WINEPREFIX="${TAPPO_PREFIX}"
export WINEDEBUG=-all

# 3. Initialize prefix if new
if [ ! -f "${TAPPO_PREFIX}/system.reg" ]; then
    echo "[setup] Initializing Wine prefix..."
    WINEDLLOVERRIDES="mscoree=;winemenubuilder.exe=" "${WINE}" wineboot -u
fi

# 4. Configure registry for ARGB 32-bit transparency and WebView2 Windows 8 compatibility
echo "[setup] Configuring Wine registry settings..."
"${WINE}" reg add 'HKCU\Software\Wine\X11 Driver' /v ScreenDepth /t REG_SZ /d 32 /f >/dev/null 2>&1
"${WINE}" reg add 'HKCU\Software\Wine\AppDefaults\msedgewebview2.exe' /v Version /t REG_SZ /d win8 /f >/dev/null 2>&1
"${WINE}" reg add 'HKCU\Software\Wine\AppDefaults\WuwaTappo.exe\DllOverrides' /v ole32 /t REG_SZ /d native,builtin /f >/dev/null 2>&1

# 5. Patch ole32.dll inside prefix
echo "[setup] Patching ole32.dll for WineHQ Bug 60225..."
mkdir -p "${TAPPO_PREFIX}/drive_c/windows/system32"
"${WINESERVER}" -k >/dev/null 2>&1 || true
python3 "${REPO_DIR}/patches/patch_ole32.py" \
    "${RUNTIME_DIR}/lib/wine/x86_64-windows/ole32.dll" \
    "${TAPPO_PREFIX}/drive_c/windows/system32/ole32.dll"

# 6. Realign PE sections to 4KB boundaries (drops RAM from 8GB to ~1.5GB)
echo "[setup] Realigning PE sections (msedge.dll and WuwaTappo.exe)..."
python3 "${REPO_DIR}/patches/align_pe.py" "${TAPPO_PREFIX}"

# 7. Compile C sidecars
echo "[setup] Compiling C sidecars..."
gcc -O2 -Wall "${REPO_DIR}/sidecars/tappo_bridge.c" -o "${REPO_DIR}/sidecars/tappo_bridge"

if command -v x86_64-w64-mingw32-gcc >/dev/null 2>&1; then
    x86_64-w64-mingw32-gcc -O2 -Wall "${REPO_DIR}/sidecars/tappo_helper.c" -o "${REPO_DIR}/sidecars/tappo_helper.exe" -luser32
else
    "${RUNTIME_DIR}/bin/winegcc" -m64 -O2 -Wall "${REPO_DIR}/sidecars/tappo_helper.c" -o "${REPO_DIR}/sidecars/tappo_helper.exe" -luser32
fi

cp -f "${REPO_DIR}/sidecars/tappo_helper.exe" "${TAPPO_PREFIX}/drive_c/windows/tappo_helper.exe"

# 8. Check input group membership for global typing
if ! groups | grep -q "\binput\b"; then
    echo "----------------------------------------------------------------------"
    echo "[setup] NOTE: Your user is not in the 'input' group."
    echo "  To allow Wuwa Tappo to count taps while typing in other applications:"
    echo "    sudo usermod -a -G input $USER"
    echo "  Then log out and log back in."
    echo "----------------------------------------------------------------------"
fi

echo "[setup] Setup complete! You can now run ./wuwa-tappo"
