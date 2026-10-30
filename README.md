# Wuwa Tappo on Wine/Proton (Linux)

Companion launcher + compat patches to run **Wuwa Tappo** (`com.kuro.wuwatappo.global`,
Tauri 2 + WebView2 pet-overlay app) **as-is** under Proton/Wine inside the Wuthering
Waves Steam prefix (App ID `3513350`). No re-implementation, no native port — the app
updates itself and keeps its server-side features intact.

**Status: working.** The pet renders, animates, and sits on every virtual desktop.
Known remaining rough edges are listed in [Troubleshooting](#troubleshooting).

## How it works

Three mechanisms, applied automatically by the launcher:

| # | Problem | Fix |
|---|---------|-----|
| 1 | `RevokeDragDrop` cross-process crash: Tauri registers drag-drop from the browser process, revokes from the app process; Wine `ole32` dereferences a foreign-process pointer → `c0000005` on the main thread, app dies silently after ~35 s ([WineHQ bug 60225](https://bugs.winehq.org/show_bug.cgi?id=60225)) | Binary patch of Proton's `ole32.dll`: `RevokeDragDrop` entry rewritten to `xor eax,eax; ret` (`S_OK`). `RegisterDragDrop` stays intact |
| 2 | WebView2 first frame never presented on Wine: Chromium ignores 1-px window-bounds deltas, so the surface created at launch is never re-created (white/blank window) | `tappo_sidecar.py` runs inside the prefix and does a `SetWindowPos` **+4 px nudge cycle** on every `Tauri Window` top-level, re-nudging new windows (update dialog, About, …) for 8 min |
| 3 | Pet overlay stuck on one virtual desktop; screenshots/monitoring from other desktops see stale content | `sticky_daemon.py` sets EWMH `_NET_WM_DESKTOP = 0xFFFFFFFF` (sticky) on all app X11 windows within 5 s of them appearing |

`webview2_render_fix.py` is the original single-window nudge (kept for
reference/debug; `tappo_sidecar.py` supersedes it but is launched after it, harmlessly).

The launcher also exports the WebView2 Chromium flags that stop the GPU-process
crash-loop inside the bwrap container (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`,
see `ok-wuwa` for the flag set rationale) and pins the runtime via
`WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`.

## Requirements

- Steam (Flatpak or native) with a **Proton build whose `ole32.dll` matches the
  patch script's expectations** (tested: DW-Proton Latest). Any Proton ≥ 7 should
  have the same `RevokeDragDrop` structure, but the script verifies before patching.
- Wuthering Waves installed via Steam (provides the `3513350` compat prefix), or
  any prefix with `STEAM_COMPAT_DATA_PATH`.
- The WebView2 Runtime installed in the prefix at
  `C:\Program Files (x86)\Microsoft\EdgeWebView\Application\<version>` and the
  ok-ww bundled `python.exe` (see below) — the sidecars run under it.

> **ok-ww note:** this project borrows the bundled Python interpreter from the
> [ok-wuwa](https://github.com/ok-wuwa/ok-wuwa) project's install layout
> (`.../ok-ww/data/apps/ok-ww/python/python.exe`). Install ok-ww's app once, or
> drop any Windows CPython 3.12 `python.exe` at the same path / adjust
> `PYTHON_WIN` in `wuwa-tappo`.

## Setup

```sh
# 1. Clone somewhere and read the top of the script for the knobs
git clone https://github.com/khoipm06/wuwa-tappo-wine.git
cd wuwa-tappo-wine

# 2. Point the launcher at your Steam/Proton/prefix (defaults are for the
#    Flatpak Steam + LData library layout; edit the variables at the top).

# 3. Install the launcher + sidecars into the prefix
./setup.sh            # copies sidecars into $COMPAT_DATA/pfx, patches ole32.dll
```

`setup.sh` is idempotent: it verifies the `ole32.dll` patch by hash, keeps a
`.bak` of the stock DLL, and only rewrites the file when the patch is missing.

## Run

```sh
~/.local/bin/wuwa-tappo        # or ./wuwa-tappo from the clone
```

What you should see: wine boot (~10 s) → pet appears bottom-right →
nudge sidecar forces every window to paint within a few seconds →
sticky daemon pins all windows to every virtual desktop.

Kill with `Ctrl+C` on the launcher, or stop the app from its tray menu.

## Updating the app

The app's own updater works (it opens the 强制更新 dialog and installs 1.0.3
in-prefix). Let it update — the whole point of this approach is that the app
stays stock and self-updates. After an update, re-run nothing; the patches are
app-agnostic (they patch Wine, not the app).

## Repo layout

```
wuwa-tappo                 bash launcher: singleton guard, PID-tree reaper,
                           env plumbing, sidecar + sticky daemon lifecycle
setup.sh                   installs sidecars + applies/verifies the ole32 patch
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

- **White/black windows:** the nudge sidecar didn't run or the window appeared
  after its 8-min watch. Run `python3 sidecars/tappo_sidecar.py` equivalents
  manually (`python.exe Z:\...\tappo_sidecar.py`) or restart the launcher.
- **App exits silently:** almost always the ole32 patch missing (updated Proton
  overwrote the DLL). Re-run `setup.sh`.
- **Pet doesn't appear on all desktops:** `sticky_daemon.py` not running
  (it is started by the launcher; check `/tmp/wuwa_sticky.log`).
- **Duplicate taskbar icons:** a second launcher instance was started; the
  singleton guard now prevents this, close the stale ones from the tray.

## Acknowledgements

- [ok-wuwa](https://github.com/ok-wuwa/ok-wuwa) — the okww launcher pattern
  (same prefix, bundled python, `SetWindowPos` nudge) this project builds on.
- WineHQ bug 60225 for the `RevokeDragDrop` cross-process crash analysis.

## License

MIT
