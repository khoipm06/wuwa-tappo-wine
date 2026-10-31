#!/usr/bin/env bash
# Install sidecars into the Steam compat prefix and apply the ole32 patch.
# Idempotent: re-running never duplicates work or double-patches.
set -euo pipefail

APP_ID="${APP_ID:-3513350}"
STEAM_CLIENT="${STEAM_CLIENT:-$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam}"
COMPAT_DATA="${COMPAT_DATA:-/var/mnt/LData/SteamLibrary/steamapps/compatdata/${APP_ID}}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -d "${COMPAT_DATA}/pfx" ] || { echo "Prefix not found: ${COMPAT_DATA}/pfx" >&2; exit 1; }

# 1. Locate the Proton currently used for this prefix (or override with PROTON_BIN)
if [ -z "${PROTON_BIN:-}" ]; then
    PROTON_BIN="$(find "${STEAM_CLIENT}/compatibilitytools.d" -maxdepth 2 -name proton -type f 2>/dev/null | sort | tail -1)"
fi
[ -n "${PROTON_BIN}" ] && [ -x "${PROTON_BIN}" ] || { echo "Proton binary not found; set PROTON_BIN=" >&2; exit 1; }
TOOL_DIR="$(dirname "${PROTON_BIN}")"
OLE32="${TOOL_DIR}/files/lib/wine/x86_64-windows/ole32.dll"

echo "Proton: ${TOOL_DIR}"
echo "Prefix: ${COMPAT_DATA}"

# 2. Install sidecars (only if content differs)
for f in tappo_sidecar.py sticky_daemon.py webview2_render_fix.py; do
    if ! cmp -s "sidecars/${f}" "${COMPAT_DATA}/pfx/${f}" 2>/dev/null; then
        install -m 0644 "sidecars/${f}" "${COMPAT_DATA}/pfx/${f}"
        echo "installed: ${COMPAT_DATA}/pfx/${f}"
    fi
done

# 3. Install launcher into ~/.local/bin
mkdir -p "${HOME}/.local/bin"
install -m 0755 wuwa-tappo "${HOME}/.local/bin/wuwa-tappo"
echo "installed: ${HOME}/.local/bin/wuwa-tappo"

# 4. Install KWin sticky script (optional, KDE Plasma Wayland)
KWIN_SCRIPT_DIR="${HOME}/.local/share/kwin/scripts/wuwa-sticky"
if [ -d "${REPO_DIR}/kwin/wuwa-sticky" ]; then
    mkdir -p "${KWIN_SCRIPT_DIR}/contents/code"
    install -m 0644 "${REPO_DIR}/kwin/wuwa-sticky/metadata.json" "${KWIN_SCRIPT_DIR}/metadata.json"
    install -m 0644 "${REPO_DIR}/kwin/wuwa-sticky/contents/code/main.js" "${KWIN_SCRIPT_DIR}/contents/code/main.js"
    if command -v kwriteconfig6 >/dev/null 2>&1; then
        kwriteconfig6 --file kwinrc --group Plugins --key wuwa-stickyEnabled true
        if command -v qdbus-qt6 >/dev/null 2>&1; then
            qdbus-qt6 org.kde.KWin /KWin reconfigure 2>/dev/null || true
        fi
        echo "installed & enabled: KWin sticky script (wuwa-sticky)"
    fi
fi

# 5. Apply/verify the ole32 patch
if [ -f "${OLE32}" ]; then
    python3 patches/patch_ole32.py "${OLE32}"
else
    echo "WARNING: ${OLE32} not found — patch skipped; the app will crash after ~35 s." >&2
    exit 2
fi

echo "Setup complete. Run: ~/.local/bin/wuwa-tappo"
