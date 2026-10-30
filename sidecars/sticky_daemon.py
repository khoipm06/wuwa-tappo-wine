#!/usr/bin/env python3
"""sticky_daemon.py — keep WuwaTappo X11 windows on all virtual desktops
(EWMH _NET_WM_DESKTOP = 0xFFFFFFFF, sticky). Host-side; polls every 5 s and
claims windows as they appear (main, Toast, update dialog, About, ...).

Usage: python3 sticky_daemon.py [--once]
"""
import ctypes, ctypes.util, os, sys, time

x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
XOpenDisplay = x11.XOpenDisplay; XOpenDisplay.argtypes = [ctypes.c_char_p]; XOpenDisplay.restype = ctypes.c_void_p
XDefaultRootWindow = x11.XDefaultRootWindow; XDefaultRootWindow.argtypes = [ctypes.c_void_p]; XDefaultRootWindow.restype = ctypes.c_ulong
XInternAtom = x11.XInternAtom; XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]; XInternAtom.restype = ctypes.c_ulong
XGetWindowProperty = x11.XGetWindowProperty
XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                               ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                               ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
XChangeProperty = x11.XChangeProperty
XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
XGetWMName = x11.XGetWMName
class XTextProp(ctypes.Structure):
    _fields_ = [("value", ctypes.c_char_p), ("encoding", ctypes.c_ulong), ("format", ctypes.c_int), ("nitems", ctypes.c_ulong)]
XGetWMName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XTextProp)]
XGetWMName.restype = ctypes.c_int
XQueryTree = x11.XQueryTree
XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_ulong)]
XGetClassHint = x11.XGetClassHint
class XCH(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_char_p), ("res_class", ctypes.c_char_p)]
XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XCH)]
XFree = x11.XFree; XFree.argtypes = [ctypes.c_void_p]

LOG = os.environ.get("WUWA_STICKY_LOG", "/tmp/wuwa_sticky.log")

def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")

def main(once=False):
    d = XOpenDisplay(os.environ.get("DISPLAY", ":0").encode())
    if not d:
        sys.exit("no display")
    root = XDefaultRootWindow(d)
    atom_net_wm_desktop = XInternAtom(d, b"_NET_WM_DESKTOP", 0)
    done = set()
    claimed = 0
    while True:
        kids = ctypes.POINTER(ctypes.c_ulong)(); n = ctypes.c_ulong(0)
        r = ctypes.c_ulong(0); p = ctypes.c_ulong(0)
        XQueryTree(d, root, ctypes.byref(r), ctypes.byref(p), ctypes.byref(kids), ctypes.byref(n))
        for i in range(n.value):
            w = kids[i]
            if w in done:
                continue
            ch = XCH()
            if not XGetClassHint(d, w, ctypes.byref(ch)):
                continue
            cls = ch.res_class.decode() if ch.res_class else ""
            if cls != "steam_proton":
                continue
            tp = XTextProp()
            if XGetWMName(d, w, ctypes.byref(tp)) and tp.value:
                name = tp.value.decode("utf-8", "replace")
            else:
                name = ""
            # Only claim WuwaTappo-owned windows (all steam_proton wine windows
            # in this prefix belong to the app; game would be steam_app_*).
            if not name:
                continue
            val = ctypes.c_ulong(0xFFFFFFFF)
            XChangeProperty(d, w, atom_net_wm_desktop, 6, 32, 0, ctypes.byref(val), 1)  # 6=CARDINAL, PropModeReplace
            done.add(w)
            claimed += 1
            log(f"sticky: {w:#x} {name!r}")
        if once:
            break
        time.sleep(5)

if __name__ == "__main__":
    main(once="--once" in sys.argv)
