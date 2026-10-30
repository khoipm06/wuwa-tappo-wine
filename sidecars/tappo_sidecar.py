#!/usr/bin/env python3
"""WuwaTappo sidecar: nudge every visible 'Tauri Window' top-level (+4px cycle)
to force WebView2 surface re-creation / first-frame presentation. New windows
(update dialog, About, settings) appearing later get nudged once as well.

Runs inside the wine prefix via the ok-ww bundled python.exe:
  python.exe Z:\\...\\tappo_sidecar.py
Exit: 0 after the watch window elapses; 1 = none of the nudges verified.
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
WATCH_SECONDS = 480          # keep watching for new windows for 8 min
RE_NUDGE_AFTER = 240         # re-nudge a window if still unpainted after 4 min

seen = {}  # hwnd -> last nudge time


def log(msg):
    """Append to webview2_render_fix.log beside this script, falling back to
    %TEMP% (mirrors webview2_render_fix.py for read-only script dirs)."""
    import os
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " [sidecar] " + msg + "\n"
    paths = []
    if sys.argv and sys.argv[0]:
        paths.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "webview2_render_fix.log"))
    paths.append(os.path.join(os.environ.get("TEMP", os.environ.get("TMP", ".")), "webview2_render_fix.log"))
    for p in paths:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            continue
    print(line, end="")


@WNDENUMPROC
def cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value == "Tauri Window" and user32.IsWindowVisible(hwnd):
        seen.setdefault(hwnd, 0.0)
    return True


def rect_of(h):
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r


def nudge(hwnd):
    r = rect_of(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    ok1 = user32.SetWindowPos(hwnd, 0, r.left, r.top, w + 4, h + 4, SWP_NOZORDER | SWP_NOACTIVATE)
    time.sleep(1.2)
    ok2 = user32.SetWindowPos(hwnd, 0, r.left, r.top, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
    return bool(ok1 and ok2)


def main():
    start = time.time()
    any_ok = False
    while time.time() - start < WATCH_SECONDS:
        user32.EnumWindows(cb, 0)
        now = time.time()
        for hwnd in list(seen):
            if now - seen[hwnd] < RE_NUDGE_AFTER:
                continue
            if not user32.IsWindowVisible(hwnd):
                continue
            tbuf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, tbuf, 256)
            ok = nudge(hwnd)
            seen[hwnd] = now
            if ok:
                any_ok = True
                log(f"nudge hwnd={hwnd:#x} title={tbuf.value!r} OK")
            else:
                log(f"nudge hwnd={hwnd:#x} title={tbuf.value!r} FAIL")
        time.sleep(2.0)
    log(f"watch done ({len(seen)} windows seen)")
    sys.exit(0 if any_ok or seen else 1)


if __name__ == "__main__":
    main()
