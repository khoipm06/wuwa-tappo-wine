#!/usr/bin/env python3
"""
webview2_render_fix.py - Render fix for the OK-WuWa Tauri + WebView2 launcher on Wine/Proton.

On Wine, WebView2/Chromium ignores window bounds deltas of 1px, so the
compositor surface created at launch is never re-created and the first frame
is never presented (blank white window). A SetWindowPos cycle of >=2px forces
Chromium to re-create its surface and present.

This helper waits for the ok-ww launcher window and its webview page widget,
then performs a +4px SetWindowPos cycle on the top-level Tauri window,
verifying between the two steps that the WRY_WEBVIEW child followed the
resize. It retries up to 3 times; the target process is never touched
beyond the two SetWindowPos calls.

Run inside the Wine prefix via the app's bundled python.exe:
  python.exe Z:/path/to/webview2_render_fix.py

Exit codes: 0 = kick applied and verified, 1 = failed after retries,
            2 = no ok-ww window found in time.
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
user32.EnumChildWindows.restype = wt.BOOL
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetWindowPos.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
NUDGE_DELTA = 4
WINDOW_TIMEOUT = 300
STABLE_WAIT = 1.5
NUDGE_HOLD = 1.5
MAX_RETRIES = 3

_found_top = [0]
_found_webview = [0]
_found_page = [0]


@WNDENUMPROC
def _top_cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value == "Tauri Window" and user32.IsWindowVisible(hwnd):
        _found_top[0] = hwnd
        return False
    return True


@WNDENUMPROC
def _webview_cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value == "WRY_WEBVIEW":
        _found_webview[0] = hwnd
        return False
    return True


@WNDENUMPROC
def _page_cb(hwnd, _):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    if buf.value == "Chrome_WidgetWin_1":
        tbuf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, tbuf, 256)
        if tbuf.value:
            _found_page[0] = hwnd
            return False
    return True


def rect_of(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def size_of(hwnd):
    r = rect_of(hwnd)
    return (r.right - r.left, r.bottom - r.top)


def find_window():
    deadline = time.time() + WINDOW_TIMEOUT
    last_size = None
    while time.time() < deadline:
        _found_top[0] = 0
        user32.EnumWindows(_top_cb, 0)
        hwnd = _found_top[0]
        if hwnd:
            _found_webview[0] = 0
            _found_page[0] = 0
            user32.EnumChildWindows(hwnd, _webview_cb, 0)
            user32.EnumChildWindows(hwnd, _page_cb, 0)
            if _found_webview[0] and _found_page[0]:
                s = size_of(hwnd)
                if s == last_size:
                    return hwnd, _found_webview[0]
                last_size = s
        time.sleep(STABLE_WAIT)
    return 0, 0


def nudge(hwnd, webview, size):
    w, h = size
    r = rect_of(hwnd)
    user32.SetWindowPos(hwnd, 0, r.left, r.top, w + NUDGE_DELTA, h + NUDGE_DELTA, SWP_NOZORDER | SWP_NOACTIVATE)
    followed = size_of(webview) != size
    time.sleep(NUDGE_HOLD)
    user32.SetWindowPos(hwnd, 0, r.left, r.top, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
    return followed


def log(msg):
    """Append to webview2_render_fix.log; fall back to %TEMP% when the
    script directory is read-only (flatpak :ro share / container mounts)."""
    path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "webview2_render_fix.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
        return
    except OSError:
        pass
    fallback = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", ".")), "webview2_render_fix.log")
    try:
        with open(fallback, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
    except OSError:
        pass


def main():
    hwnd, webview = find_window()
    if not hwnd:
        log("failed: no window")
        sys.exit(2)
    size = size_of(hwnd)
    for attempt in range(MAX_RETRIES):
        if nudge(hwnd, webview, size):
            log(f"nudge ok (attempt {attempt + 1})")
            sys.exit(0)
        time.sleep(2)
    log("nudge failed: child did not follow resize")
    sys.exit(1)


if __name__ == "__main__":
    main()
