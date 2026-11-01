# Root-cause chain: Wuwa Tappo under Proton/Wine

Reverse-chronological summary of the debugging campaign (Oct 28–31, 2026),
with the evidence that killed each hypothesis. Read this before changing
anything in the launcher — every workaround below was empirically verified.

## TL;DR

Three independent defects stacked on each other:

1. **WebView2 GPU crash-loop** (fixed by Chromium flags)
2. **Wine `RevokeDragDrop` cross-process `c0000005`** (fixed by binary patch)
3. **First frame never presented on Wine** (fixed by `SetWindowPos` nudge ≥ 2 px)

Plus quality-of-life: sticky windows for multi-desktop use.

---

## 1. GPU process crash-loop

**Symptom:** white window; `EBWebView/chrome_debug.log` ends with
`FATAL: GPU process isn't usable. Goodbye.` after 6 GPU-process crashes;
`DCompositionCreateDevice3 failed: Not implemented (0x80004001)`.

**Mechanism:** WebView2's DComp paths have no Wine implementation. Wine's
`dcomp.dll` is stub-only (~17 exports, mostly `__wine_stub_`), so every
DirectComposition call returns `E_NOTIMPL` and Chromium's GPU process dies in
a loop; after 6 crashes the browser gives up and exits.

**Fix:** launch flags via `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`
(see [flags.md](flags.md)): `--no-sandbox --disable-gpu --in-process-gpu …`
and the `DirectComposition*` feature blocks. With `--in-process-gpu` the
crash-loop disappears entirely (no separate GPU process to crash).

**Later finding:** with a *real* GPU process (flags absent, DXVK present) the
DComp path through DXVK also presents — the flags are only required inside the
pressure-vessel/bwrap container where the sandbox paths break. Both
configurations verified stable.

## 2. RevokeDragDrop cross-process crash (the silent killer)

**Symptom:** after flags fixed the boot, app still died silently 35 s – 4 min
in. No exception in the app log, no crashpad dump, no `err:` output.

**Investigation:** `WINEDEBUG=+seh` surfaced
`c0000005` at `ole32+0x3a2cd` on the main thread. The offset lands inside
`RevokeDragDrop`, on `mov (%rax),%rax` — dereferencing a drop-target pointer
registered by **another process** (WebView2 browser process).

**Mechanism (WineHQ bug 60225):** Tauri calls `RegisterDragDrop(hwnd, ptr)`
which in WebView2's environment runs in the browser process; later
`RevokeDragDrop(hwnd)` executes in the app process. Wine's implementation
dereferences the pointer directly (no cross-process marshalling) →
`c0000005`.

**Fix:** binary patch of Proton's `ole32.dll`:
`RevokeDragDrop` prologue → `31 C0 C3` (`xor eax,eax; ret` = `S_OK`).
`RegisterDragDrop` left intact. `patches/patch_ole32.py` does this
defensively (export-table lookup, prologue verification, `.bak`).

**Verification:** post-patch sessions ran 20–60+ min with zero
`c0000005`, zero GPU exits, zero new crashpad dumps.

## 3. First frame never presented & Drag Glitching

**Symptom:** Without fixes, windows mapped and processes healthy, but pixels never changed
(pure white surface). Under software rendering workarounds, dragging the pet caused
continuous flashing of black and white checkerboard tiles.

**Mechanism:**
1. **First-frame freeze**: Chromium enables `CalculateNativeWinOcclusion` on Windows.
   Because Wine lacks DWM occlusion tracking, `WS_EX_LAYERED | WS_EX_TRANSPARENT` windows
   were falsely flagged as `OCCLUDED`, causing Chromium to freeze compositor frame presentation.
2. **Dragging glitch (checkerboarding)**: Forcing software compositing offloaded rasterization
   to the CPU. When dragging, mouse events overwhelmed the CPU rasterizer, missing frame deadlines
   and triggering `cc::SoftwareRenderer` checkerboard fallback (white/black placeholder tiles).

**Clean Fix (No sidecars or position nudges needed):**
- Launch flags:
  `--in-process-gpu --disable-direct-composition --disable-features=CalculateNativeWinOcclusion,DirectComposition,DirectCompositionLayers... --disable-checker-imaging --disable-partial-raster`
- Runs GPU rendering directly via DXVK swapchain inside the process.
- Frame 1 presents immediately without `SetWindowPos` hacks.
- Dragging is silky smooth with zero tile tearing.

## 4. Multi-desktop & observability

User switches virtual desktops; the overlay must follow (it's a pet).
Host-side `sticky_daemon.py` sets `_NET_WM_DESKTOP = 0xFFFFFFFF` (EWMH sticky)
on every `steam_proton` X11 window with a WM name, within 5 s of it appearing.
This also makes screenshots correct from any desktop.

## Tooling notes (for future debugging)

- `pgrep -c -f` self-matches the scanning shell — count via `/proc/*/comm`.
- A second `flatpak run --command=…` into the same Steam app can kill the
  running instance (flatpak single-instance); monitor host-side via `/proc`.
- `wineserver -k` discards un-flushed `reg add` writes; verify with
  `wine reg query` in the same session before killing.
- ctypes X11 calls segfault without explicit `argtypes`; `XGetImage` on the
  root window fails under XWayland (use `spectacle` or window-local sampling).
- Env-var flag delivery (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`) reached the
  browser process environ but not its argv in one session; the HKLM
  policy `…\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments`
  = `WuwaTappo.exe` is the reliable channel (see flags.md).
