#!/usr/bin/env bash
# Install sidecars into the Steam compat prefix and apply the ole32 patch.
# Idempotent: re-running never duplicates work or double-patches.
set -euo pipefail

APP_ID="${APP_ID:-3513350}"
STEAM_CLIENT="${WUWA_STEAM_CLIENT:-${STEAM_CLIENT:-$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam}}"
COMPAT_DATA="${WUWA_COMPAT_DATA:-${COMPAT_DATA:-/var/mnt/LData/SteamLibrary/steamapps/compatdata/${APP_ID}}}"
PROTON_BIN="${WUWA_PROTON:-${PROTON_BIN:-}}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -d "${COMPAT_DATA}/pfx" ] || { echo "Prefix not found: ${COMPAT_DATA}/pfx" >&2; exit 1; }

# 1. Locate the Proton currently used for this prefix (or override with PROTON_BIN)
if [ -z "${PROTON_BIN:-}" ]; then
    if [ -x "${STEAM_CLIENT}/compatibilitytools.d/DW-Proton Latest/proton" ]; then
        PROTON_BIN="${STEAM_CLIENT}/compatibilitytools.d/DW-Proton Latest/proton"
    else
        PROTON_BIN="$(find "${STEAM_CLIENT}/compatibilitytools.d" -maxdepth 2 -name proton -type f 2>/dev/null | sort | tail -1)"
    fi
fi
[ -n "${PROTON_BIN}" ] && [ -x "${PROTON_BIN}" ] || { echo "Proton binary not found; set PROTON_BIN=" >&2; exit 1; }
TOOL_DIR="$(dirname "${PROTON_BIN}")"
OLE32="${TOOL_DIR}/files/lib/wine/x86_64-windows/ole32.dll"

echo "Proton: ${TOOL_DIR}"
echo "Prefix: ${COMPAT_DATA}"

# Preflight: Verify host X11 libraries required by sticky_daemon
python3 -c '
import ctypes.util, sys
missing = []
for lib in ("X11", "Xext"):
    if not ctypes.util.find_library(lib):
        missing.append(f"lib{lib}")
if missing:
    sys.stderr.write(f"WARNING: Host libraries missing: {missing}. sticky_daemon may fail.\n")
' || true

# Preflight: Verify in-prefix Python runtime for sidecars
PYTHON_WIN_HOST="${COMPAT_DATA}/pfx/drive_c/users/steamuser/AppData/Local/ok-ww/data/apps/ok-ww/python/python.exe"
if [ ! -f "${PYTHON_WIN_HOST}" ] && [ -z "${WUWA_PYTHON_WIN:-}" ]; then
    echo "NOTE: Default in-prefix python.exe not found at: ${PYTHON_WIN_HOST}"
    echo "      If ok-ww is not installed, provide WUWA_PYTHON_WIN= to run sidecars."
fi

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
    else
        echo "notice: kwriteconfig6 not found; skipping KWin script (sticky_daemon handles stickiness)"
    fi
fi

# 5. Apply/verify the ole32 patch
if [ -f "${OLE32}" ]; then
    python3 patches/patch_ole32.py "${OLE32}"
else
    echo "WARNING: ${OLE32} not found — patch skipped; the app will crash after ~35 s." >&2
    exit 2
fi

# 6. Configure Wine prefix registry for 32-bit ARGB TrueColor visual under XWayland
USER_REG="${COMPAT_DATA}/pfx/user.reg"
if [ -f "${USER_REG}" ]; then
    python3 - << 'EOF' "${USER_REG}"
import os, re, sys

user_reg = sys.argv[1]
with open(user_reg, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

targets = [
    r"Software\\Wine\\AppDefaults\\WuwaTappo.exe\\X11 Driver",
    r"Software\\Wine\\AppDefaults\\msedgewebview2.exe\\X11 Driver",
    r"Software\\Wine\\X11 Driver",
]

single_bs_targets = [
    r"Software\Wine\AppDefaults\WuwaTappo.exe\X11 Driver",
    r"Software\Wine\AppDefaults\msedgewebview2.exe\X11 Driver",
    r"Software\Wine\X11 Driver",
]

modified = False

# 1. Clean up any malformed single-backslash versions
# 1. Clean up any malformed single-backslash versions
for s_target in single_bs_targets:
    esc_s = re.escape(s_target)
    pat_s = rf"^\[{esc_s}\](?:[ \t]+\d+)?\r?\n(.*?)(?=^\[|\Z)"
    if re.search(pat_s, content, flags=re.MULTILINE | re.DOTALL):
        content = re.sub(pat_s, "", content, flags=re.MULTILINE | re.DOTALL)
        modified = True

# 2. Check each target and ensure ScreenDepth="32" exactly once
for target in targets:
    esc = re.escape(target)
    pat = rf"^\[{esc}\](?:[ \t]+\d+)?\r?\n(.*?)(?=^\[|\Z)"
    matches = list(re.finditer(pat, content, flags=re.MULTILINE | re.DOTALL))

    if not matches:
        if not content.endswith("\n"):
            content += "\n"
        content += f"[{target}]\n\"ScreenDepth\"=\"32\"\n\n"
        modified = True
    else:
        if len(matches) > 1:
            for dup in reversed(matches[1:]):
                content = content[:dup.start()] + content[dup.end():]
            modified = True
            m = re.search(pat, content, flags=re.MULTILINE | re.DOTALL)
        else:
            m = matches[0]

        body = m.group(1)
        if not re.search(r'^\s*"ScreenDepth"\s*=\s*"32"', body, flags=re.MULTILINE):
            header_end = content.find("\n", m.start()) + 1
            header_line = content[m.start():header_end]
            clean_body = re.sub(r'^\s*"ScreenDepth"\s*=.*\r?\n?', '', body, flags=re.MULTILINE)
            time_m = re.search(r'^#time=[^\n]*\n', clean_body, flags=re.MULTILINE)
            if time_m:
                new_body = clean_body[:time_m.end()] + '"ScreenDepth"="32"\n' + clean_body[time_m.end():]
            else:
                new_body = '"ScreenDepth"="32"\n' + clean_body
            new_section = header_line + new_body
            content = content[:m.start()] + new_section + content[m.end():]
            modified = True

if modified:
    content = content.rstrip() + "\n"
    with open(user_reg, 'w', encoding='utf-8') as f:
        f.write(content)
EOF

    ENTRY_POINT="${WUWA_ENTRY_POINT:-/var/mnt/LData/SteamLibrary/steamapps/common/SteamLinuxRuntime_4/_v2-entry-point}"
    if [ -x "${ENTRY_POINT}" ] && command -v flatpak >/dev/null 2>&1; then
        flatpak run \
            --env=STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_CLIENT}" \
            --env=STEAM_COMPAT_DATA_PATH="${COMPAT_DATA}" \
            --command="${ENTRY_POINT}" \
            com.valvesoftware.Steam \
            --verb=runinprefix -- bash -c "
                '${PROTON_BIN}' runinprefix reg add 'HKCU\\Software\\Wine\\AppDefaults\\WuwaTappo.exe\\X11 Driver' /v ScreenDepth /t REG_SZ /d '32' /f >/dev/null 2>&1 || true
                '${PROTON_BIN}' runinprefix reg add 'HKCU\\Software\\Wine\\AppDefaults\\msedgewebview2.exe\\X11 Driver' /v ScreenDepth /t REG_SZ /d '32' /f >/dev/null 2>&1 || true
                '${PROTON_BIN}' runinprefix reg add 'HKCU\\Software\\Wine\\X11 Driver' /v ScreenDepth /t REG_SZ /d '32' /f >/dev/null 2>&1 || true
            " >/dev/null 2>&1 || true
    fi
    echo "configured: Wine prefix ScreenDepth=32 (32-bit ARGB TrueColor visual)"
fi

echo "Setup complete. Run: ~/.local/bin/wuwa-tappo"

