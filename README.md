# Wuwa Tappo on Wine/Proton (Linux)

Companion launcher + compat patches to run **Wuwa Tappo** (`com.kuro.wuwatappo.global`,
Tauri 2 + WebView2 pet-overlay app) **as-is** under Proton/Wine.

The app lives in its **own dedicated Wine prefix**, completely separate from the
Wuthering Waves game prefix (`compatdata/3513350`). Nothing here patches Proton,
touches the game prefix, or changes any global Wine setting — the game is
unaffected and anti-cheat sees a stock environment.

**Status: working.** The pet renders, animates, and sits on every virtual desktop.

## How it works

Three mechanisms, applied automatically by the launcher. All of them are scoped
to the Tappo prefix / Tappo processes only.

| # | Problem | Fix |
|---|---------|-----|
| 1 | `RevokeDragDrop` cross-process crash: Tauri registers drag-drop from the browser process, revokes from the app process; Wine `ole32` dereferences a foreign-process pointer → `c0000005` on the main thread, app dies silently after ~35 s ([WineHQ bug 60225](https://bugs.winehq.org/show_bug.cgi?id=60225)) | Binary patch of the **prefix-local** `drive_c/windows/system32/ole32.dll`: `RevokeDragDrop` entry rewritten to `xor eax,eax; ret` (`S_OK`). `RegisterDragDrop` stays intact. The Proton-wide DLL is never modified |
| 2 | WebView2 first frame never presented on Wine: Chromium ignores 1-px window-bounds deltas, so the surface created at launch is never re-created (white/blank window) | `tappo_sidecar.py` runs inside the prefix and does a `SetWindowPos` **+4 px nudge cycle** on every visible `Tauri Window` top-level, re-nudging new windows (update dialog, About, ...) for 8 min |
| 3 | Pet overlay stuck on one virtual desktop | `sticky_daemon.py` sets EWMH `_NET_WM_DESKTOP = 0xFFFFFFFF` (sticky) on all app X11 windows within 5 s of them appearing |

`webview2_render_fix.py` is the original single-window nudge (kept for
reference/debug; `tappo_sidecar.py` supersedes it but is launched after it, harmlessly).

The launcher also exports the WebView2 Chromium flags that stop the GPU-process
crash-loop inside the bwrap container (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`,
see `docs/flags.md` for the rationale) and pins the runtime via
`WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`.

## Requirements

- Steam, Flatpak or native. Flatpak is assumed by default.
- A Proton build matching the patch script's expectations (tested: DW-Proton Latest).
  The script verifies bytes before patching.
- SteamLinuxRuntime (`_v2-entry-point`) from any Steam library — auto-detected.
- WebView2 Runtime and a Windows CPython 3.12 installed **inside the Tappo prefix**
  (see [Creating the prefix](#creating-the-prefix)).

## Prefix location — the one real gotcha

The prefix **must be writable from inside the Steam Flatpak sandbox**. Its
permissions allow `filesystems=/mnt;/media;/run/media;...;~/.var/app/com.valvesoftware.Steam`.
`$HOME` and `~/.local/share` are **not** writable there.

Use any of:

- `/mnt/<disk>/tappo-prefix`
- `/run/media/<user>/<disk>/tappo-prefix`
- `~/.var/app/com.valvesoftware.Steam/.local/share/tappo-prefix` (default for Flatpak Steam)
- `~/.local/share/tappo-prefix` (default for native Steam)

Point the launcher at your choice in `~/.config/wuwa-tappo/env`:

```sh
WUWA_COMPAT_DATA="$HOME/.var/app/com.valvesoftware.Steam/.local/share/tappo-prefix"
```

## Creating the prefix

By hand, the order matters:

```sh
COMPAT="$HOME/.var/app/com.valvesoftware.Steam/.local/share/tappo-prefix"   # must be flatpak-writable if using Flatpak Steam
PROTON="$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/compatibilitytools.d/DW-Proton Latest/proton"
# ENTRY is auto-detected by wuwa-tappo from libraryfolders.vdf, or specify manually:
# ENTRY="/path/to/SteamLinuxRuntime_4/_v2-entry-point"

fp() { flatpak run --env=STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam" \
        --env=STEAM_COMPAT_DATA_PATH="$COMPAT" --command="$ENTRY" com.valvesoftware.Steam \
        --verb=runinprefix -- bash -c "$1"; }

# 1. Init the prefix (--verb=wineboot does NOT work; runinprefix does)
fp "'$PROTON' wineboot --init"

# 2. Windows CPython for the sidecars (they need ctypes.WinDLL — host Python cannot run them)
curl -LO https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip
unzip -q python-3.12.9-embed-amd64.zip -d "$COMPAT/pfx/drive_c/tools/python"

# 3. WebView2 — the Tauri installer is itself a WebView2 app and needs it first
fp "'$PROTON' runinprefix 'C:\\path\\to\\MicrosoftEdgeWebview2Setup.exe' /silent /install"

# 4. Wuwa Tappo
fp "'$PROTON' runinprefix 'C:\\path\\to\\WuwaTappo-global_1.0.2_x64-setup.exe' /S"
```

Then `./setup.sh` installs the sidecars, patches the prefix-local `ole32.dll`,
and sets `ScreenDepth=32` on the two AppDefaults keys only.

## Setup

```sh
git clone https://github.com/khoipm06/wuwa-tappo-wine.git
cd wuwa-tappo-wine
# If your prefix is not at default location:
# export WUWA_COMPAT_DATA=/path/to/tappo-prefix
./setup.sh
```

`setup.sh` is idempotent: it verifies the `ole32.dll` patch by hash and only rewrites the file when the patch is missing.

## Run

```sh
~/.local/bin/wuwa-tappo        # or ./wuwa-tappo from the clone
```

What you should see: wine boot (~10 s) → pet appears bottom-right →
nudge sidecar forces every window to paint within a few seconds →
sticky daemon pins all windows to every virtual desktop.

Kill with `Ctrl+C` on the launcher, or stop the app from its tray menu.

## Updating the app

The app's own updater works (it opens the 强制更新 dialog and installs updates
in-prefix). Let it update — the whole point of this approach is that the app
stays stock and self-updates. The patches are app-agnostic: they patch Wine and
window geometry, not the app binary.

## Repo layout

```
wuwa-tappo                 bash launcher: singleton guard, PID-tree reaper,
                           env plumbing, sidecar + sticky daemon lifecycle
setup.sh                   installs sidecars, KWin script + applies/verifies ole32 patch
kwin/
  wuwa-sticky/             KWin script package to keep pet sticky and borderless on KDE
patches/
  patch_ole32.py           binary patcher: locates RevokeDragDrop via the PE
                           export table, verifies original bytes, writes
                           xor eax,eax; ret, keeps ole32.dll.bak
sidecars/
  tappo_sidecar.py         nudge-all windows (8-min watch, 4-min re-nudge)
  sticky_daemon.py         host-side: sticky windows (EWMH) for all app windows
  webview2_render_fix.py   original single-window nudge (reference)
docs/
  root-cause.md            full debugging story with evidence
  flags.md                 WebView2 Chromium flags & delivery channels tested
```

## Troubleshooting

- **`Prefix not found` / flatpak `FileNotFoundError` on `pfx.lock`:** the prefix
  is not under a flatpak-visible path. See [Prefix location](#prefix-location--the-one-real-gotcha).
- **Installer hangs at ~0 % or `failed to receive message from webview`:** WebView2
  is not installed in the prefix yet. Install it before the app (step 3 above).
- **`Could not find the webview runtime`:** `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`
  points at a non-version directory. The launcher filters for `^[0-9]+\.`.
- **White/black windows:** the nudge sidecar didn't run, or the window appeared
  after its 8-min watch. Restart the launcher.
- **App exits silently:** the ole32 patch is missing (re-ran `wineboot` or wiped
  `system32`). Re-run `setup.sh`.
- **Pet doesn't appear on all desktops:** `sticky_daemon.py` not running; check
  `/tmp/wuwa_sticky_stderr.log`.

## Acknowledgements

- [ok-wuwa](https://github.com/ok-wuwa/ok-wuwa) — the okww launcher pattern
  (bundled python, `SetWindowPos` nudge) this project builds on.
- WineHQ bug 60225 for the `RevokeDragDrop` cross-process crash analysis.

## License

MIT