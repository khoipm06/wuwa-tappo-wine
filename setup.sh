#!/usr/bin/env bash
# Install sidecars into a dedicated Tappo Wine prefix and patch its ole32.dll.
# Idempotent: re-running never duplicates work or double-patches.
#
# The prefix is ISOLATED from the Wuthering Waves game prefix; no shared state.
# ole32.dll is patched inside the prefix (drive_c/windows/system32) only — the
# Proton-wide copy is never touched.
#
# Required env / overrides:
#   WUWA_COMPAT_DATA   Tappo compat dir (default: ~/.var/app/com.valvesoftware.Steam/.local/share/tappo-prefix)
#                      Must be writable inside the Steam Flatpak sandbox: /mnt, /media,
#                      /run/media, or ~/.var/app/com.valvesoftware.Steam.
#   WUWA_STEAM_CLIENT  Flatpak Steam data root        (default: ~/.var/app/…/Steam)
#   WUWA_PROTON        Proton runner binary            (default: DW-Proton Latest)
#   WUWA_ENTRY_POINT   SteamLinuxRuntime _v2-entry    (default: auto-detected)
set -euo pipefail

STEAM_CLIENT="${WUWA_STEAM_CLIENT:-${STEAM_CLIENT:-$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam}}"
COMPAT_DATA="${WUWA_COMPAT_DATA:-$HOME/.var/app/com.valvesoftware.Steam/.local/share/tappo-prefix}"
PROTON_BIN="${WUWA_PROTON:-${PROTON_BIN:-}}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -d "${COMPAT_DATA}/pfx" ] || {
    echo "Prefix not found: ${COMPAT_DATA}/pfx" >&2
    echo "Run: WUWA_COMPAT_DATA=${COMPAT_DATA} ${REPO_DIR}/setup.sh --init" >&2
    exit 1
}

# 1. Locate Proton
if [ -z "${PROTON_BIN:-}" ]; then
    if [ -x "${STEAM_CLIENT}/compatibilitytools.d/DW-Proton Latest/proton" ]; then
        PROTON_BIN="${STEAM_CLIENT}/compatibilitytools.d/DW-Proton Latest/proton"
    else
        PROTON_BIN="$(find "${STEAM_CLIENT}/compatibilitytools.d" -maxdepth 2 -name proton -type f 2>/dev/null | sort | tail -1)"
    fi
fi
[ -n "${PROTON_BIN}" ] && [ -x "${PROTON_BIN}" ] || { echo "Proton binary not found; set WUWA_PROTON=" >&2; exit 1; }

echo "Proton: ${PROTON_BIN}"
echo "Prefix: ${COMPAT_DATA}"

# 2. Preflight: host X11 libs for sticky_daemon
python3 -c '
import ctypes.util, sys
missing = [lib for lib in ("X11", "Xext") if not ctypes.util.find_library(lib)]
if missing:
    sys.stderr.write(f"WARNING: Host libraries missing: {missing}. sticky_daemon may fail.\n")
' || true

# 3. Provision Windows CPython for the sidecars.
#    The sidecars use ctypes.WinDLL/WINFUNCTYPE and cannot run on host Python,
#    so a Windows interpreter must live inside the prefix.
PY_DIR="${COMPAT_DATA}/pfx/drive_c/tools/python"
if [ ! -f "${PY_DIR}/python.exe" ]; then
    PY_VER="3.12.9"
    PY_ZIP="python-${PY_VER}-embed-amd64.zip"
    echo "provisioning Windows CPython ${PY_VER} -> ${PY_DIR}"
    mkdir -p "${PY_DIR}"
    tmp="$(mktemp -d)"
    curl -fsSL -o "${tmp}/${PY_ZIP}" "https://www.python.org/ftp/python/${PY_VER}/${PY_ZIP}"
    unzip -qo "${tmp}/${PY_ZIP}" -d "${PY_DIR}"
    rm -rf "${tmp}"
else
    echo "python: ${PY_DIR}/python.exe present"
fi

# 4. Install sidecars (only if content differs)
for f in tappo_sidecar.py sticky_daemon.py webview2_render_fix.py; do
    if ! cmp -s "sidecars/${f}" "${COMPAT_DATA}/pfx/${f}" 2>/dev/null; then
        install -m 0644 "sidecars/${f}" "${COMPAT_DATA}/pfx/${f}"
        echo "installed: ${COMPAT_DATA}/pfx/${f}"
    fi
done

# 5. Install launcher
mkdir -p "${HOME}/.local/bin"
install -m 0755 wuwa-tappo "${HOME}/.local/bin/wuwa-tappo"
echo "installed: ${HOME}/.local/bin/wuwa-tappo"

# 6. Install KWin sticky script (optional, KDE Plasma Wayland)
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
        echo "installed & enabled: KWin sticky script"
    fi
fi

# 7. Patch ole32.dll inside the prefix (prefix-local copy only — Proton untouched)
#    The prefix copy lives at drive_c/windows/system32/ole32.dll.
#    This is the DLL Wine loads for WuwaTappo.exe; patching here has zero effect
#    on any other game or app using the same Proton build.
PFX_OLE32="${COMPAT_DATA}/pfx/drive_c/windows/system32/ole32.dll"
if [ -f "${PFX_OLE32}" ]; then
    python3 patches/patch_ole32.py "${PFX_OLE32}"
else
    echo "WARNING: ${PFX_OLE32} not found." >&2
    echo "  Ensure the prefix was initialised (run: ${REPO_DIR}/setup.sh after wineboot)." >&2
    exit 2
fi

# 8. Configure Wine registry — ScreenDepth=32 (ARGB visual) for Tappo + WebView2
USER_REG="${COMPAT_DATA}/pfx/user.reg"
if [ -f "${USER_REG}" ]; then
    python3 - << 'EOF' "${USER_REG}"
import re, sys

user_reg = sys.argv[1]
with open(user_reg, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

targets = [
    r"Software\\Wine\\AppDefaults\\WuwaTappo.exe\\X11 Driver",
    r"Software\\Wine\\AppDefaults\\msedgewebview2.exe\\X11 Driver",
]

modified = False
for target in targets:
    esc = re.escape(target)
    pat = rf"^\[{esc}\](?:[ \t]+\d+)?\r?\n(?:(?!\[).*\r?\n)*"
    matches = list(re.finditer(pat, content, flags=re.MULTILINE))
    if not matches:
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n[{target}]\n\"ScreenDepth\"=\"32\"\n"
        modified = True
    else:
        block = matches[0].group(0)
        if '"ScreenDepth"="32"' not in block:
            new_block = block.rstrip('\n') + '\n"ScreenDepth"="32"\n\n'
            content = content[:matches[0].start()] + new_block + content[matches[0].end():]
            modified = True
        for dup in reversed(matches[1:]):
            content = content[:dup.start()] + content[dup.end():]
            modified = True

if modified:
    with open(user_reg, 'w', encoding='utf-8') as f:
        f.write(content)
    print("configured: ScreenDepth=32 for WuwaTappo.exe and msedgewebview2.exe")
else:
    print("registry: ScreenDepth=32 already set")
EOF
fi

echo "Setup complete. Run: wuwa-tappo"
