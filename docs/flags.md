# WebView2 Chromium flags: what was tested, what works

## The flag set

```text
--no-sandbox
--in-process-gpu
--disable-direct-composition
--disable-features=CalculateNativeWinOcclusion,DirectComposition,DirectCompositionLayers,WidgetLayering,RendererCodeIntegrity,TouchEvents,TouchSelectionStrategy,DWriteFontProxy
--disable-direct-composition-video-overlays
--disable-checker-imaging
--disable-partial-raster
--disable-backgrounding-occluded-windows
--disable-renderer-backgrounding
--disable-background-timer-throttling
--enable-features=RunAllCompositorStagesBeforeDraw
```

Rationale per group:

- `--no-sandbox` — the Chromium sandbox cannot initialize inside the
  pressure-vessel/bwrap container (nested namespace + wine style paths).
- `--in-process-gpu` — runs GPU threads within the browser process, bypassing
  WineHQ bug 59370 (cross-process NT shared handles in DXVK/Wine).
- `--disable-direct-composition` & `--disable-features=…DirectComposition…` —
  directs Chromium to use DXGI SwapChain -> DXVK -> Vulkan directly, bypassing
  Wine's stubbed `dcomp.dll` (0x80004001 E_NOTIMPL).
- `--disable-features=CalculateNativeWinOcclusion` & `--disable-backgrounding-occluded-windows` —
  Wine lacks DWM occlusion tracking, causing Chromium to mark layered transparent windows as
  occluded and freeze compositor frame presentation. Disabling native occlusion allows
  Chromium to present the first frame immediately without any external `SetWindowPos` nudge!
- `--disable-checker-imaging` & `--disable-partial-raster` — eliminates black/white checkerboard
  tile glitching when dragging/moving the pet across the screen.

## Delivery channels (this was the tricky part)

| Channel | Result |
|---------|--------|
| `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` env var | Reached the browser process environ, **but was not applied to argv** in one observed session (WebView2 loader nuance) — ok-ww in the same prefix *did* get flags through the env var |
| HKLM policy `HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments`, value name `WuwaTappo.exe` | **Reliable**: flags verified present in renderer argv |
| Registry `reg add` persistence | `reg add` writes are visible to `wine reg query` immediately but `system.reg` flush is delayed; `wineserver -k` before the flush **loses the write** |

Current launcher ships the env var; if a future WebView2 runtime ignores it,
set the HKLM policy (one `wine reg add` line, see launcher header comment).

## Real-GPU configuration (verified 2026-10-31)

A session with **no flags applied** (policy missing after prefix surgery) ran
50+ minutes with the real GPU process via DXVK and presented frames correctly.
Interpretation: the flags are required where the Chromium sandbox/DComp stack
cannot initialize (containerized Steam); on a GPU-capable wine build the
unpatched configuration can also work. The launcher keeps the env var set —
it is harmless when GPU works, and life-saving when it doesn't.
