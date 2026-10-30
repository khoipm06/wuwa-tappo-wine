# Commit 1: full working snapshot

Initial public drop. Contents verified before commit:

- `patches/patch_ole32.py` — end-to-end test on a stock ole32.dll copy:
  locates `RevokeDragDrop` via PE export table (RVA `0x34d30` on the stock
  build), verifies the expected prologue, writes `31 c0 c3`, restores
  read-only mode. Bytes after patch identical to the live patched DLL at the
  respective export RVA. Idempotency tested (`already patched` path).
- `sidecars/tappo_sidecar.py` — verified live: nudged all 4 windows
  (`Wuwa Tappo`, `Toast`, `强制更新`, `About Wuwa Tappo`) in the running
  session; text rendering appeared in screenshots after the nudge.
- `sidecars/sticky_daemon.py` — verified live: 6/6 wine windows report
  `_NET_WM_DESKTOP = 0xFFFFFFFF` (STICKY) after one pass.
- `wuwa-tappo` launcher — `bash -n` clean; winpath conversion unit-checked.
