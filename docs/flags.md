# WebView2 Chromium flags: what was tested, what works

## The flag set

```text
--no-sandbox
--disable-gpu
--disable-gpu-compositing
--disable-gpu-rasterization
--in-process-gpu
--disable-features=RendererCodeIntegrity,TouchEvents,TouchSelectionStrategy,DWriteFontProxy,DirectComposition,DirectCompositionLayers,WidgetLayering
--disable-direct-composition-video-overlays
--disable-accelerated-2d-canvas
--disable-accelerated-video-decode
```

Rationale per group:

- `--no-sandbox` — the Chromium sandbox cannot initialize inside the
  pressure-vessel/bwrap container (nested namespace + wine style paths).
- `--in-process-gpu` — removes the separate GPU process entirely, ending the
  DComp `E_NOTIMPL` crash-loop (the GPU "process" crash was the browser giving
  up after 6 child-process crashes).
- `--disable-features=…DirectComposition…` — blocks the DComp code paths that
  have no Wine implementation.
- Renderer-level disables — belt-and-braces for the software compositing path.

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
