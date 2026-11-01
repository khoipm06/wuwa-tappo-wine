#!/usr/bin/env python3
"""sticky_daemon.py — keep WuwaTappo X11 windows on all virtual desktops
(EWMH _NET_WM_DESKTOP = 0xFFFFFFFF, sticky) and synchronize XShape input shape
on DesktopCatInput so mouse clicks on transparent regions pass through cleanly
to desktop applications without lag or hook queue saturation.

Usage: python3 sticky_daemon.py [--once] [--verbose]
"""
import ctypes
import ctypes.util
import os
import select
import signal
import sys
import time

LOG_PATH = os.environ.get("WUWA_STICKY_LOG", "/tmp/wuwa_sticky.log")


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass
    if sys.stderr.isatty() or os.environ.get("WUWA_STICKY_VERBOSE"):
        sys.stderr.write(line)
        sys.stderr.flush()


# --- X11 & Xext Ctypes Bindings ---

lib_x11_path = ctypes.util.find_library("X11")
if not lib_x11_path:
    sys.exit("libX11 not found")
x11 = ctypes.CDLL(lib_x11_path)

lib_xext_path = ctypes.util.find_library("Xext")
xext = ctypes.CDLL(lib_xext_path) if lib_xext_path else None

# XShape Constants
ShapeSet = 0
ShapeUnion = 1
ShapeIntersect = 2
ShapeSubtract = 3
ShapeInvert = 4

ShapeBounding = 0
ShapeClip = 1
ShapeInput = 2

ShapeNotifyMask = 1 << 0
ShapeNotify = 0

PropModeReplace = 0
CARDINAL = 6


class XCH(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class XTextProp(ctypes.Structure):
    _fields_ = [
        ("value", ctypes.c_void_p),
        ("encoding", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("nitems", ctypes.c_ulong),
    ]


class XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


class XShapeEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("kind", ctypes.c_int),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_uint),
        ("height", ctypes.c_uint),
        ("time", ctypes.c_ulong),
        ("shaped", ctypes.c_int),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xshape", XShapeEvent),
        ("pad", ctypes.c_byte * 192),
    ]


class XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("resourceid", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


XErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))

# X11 Function Signatures
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XOpenDisplay.restype = ctypes.c_void_p

x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
x11.XCloseDisplay.restype = ctypes.c_int

x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
x11.XDefaultRootWindow.restype = ctypes.c_ulong

x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
x11.XInternAtom.restype = ctypes.c_ulong

x11.XChangeProperty.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_int,
]
x11.XChangeProperty.restype = ctypes.c_int

x11.XGetWMName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XTextProp)]
x11.XGetWMName.restype = ctypes.c_int

x11.XQueryTree.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.c_ulong),
    ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
    ctypes.POINTER(ctypes.c_ulong),
]
x11.XQueryTree.restype = ctypes.c_int

x11.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XCH)]
x11.XGetClassHint.restype = ctypes.c_int

x11.XFree.argtypes = [ctypes.c_void_p]
x11.XFree.restype = ctypes.c_int

x11.XFlush.argtypes = [ctypes.c_void_p]
x11.XFlush.restype = ctypes.c_int

x11.XPending.argtypes = [ctypes.c_void_p]
x11.XPending.restype = ctypes.c_int

x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
x11.XNextEvent.restype = ctypes.c_int

x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
x11.XConnectionNumber.restype = ctypes.c_int

x11.XSetErrorHandler.argtypes = [XErrorHandler]
x11.XSetErrorHandler.restype = XErrorHandler

# Xext Function Signatures
if xext:
    xext.XShapeQueryExtension.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    xext.XShapeQueryExtension.restype = ctypes.c_int

    xext.XShapeSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    xext.XShapeSelectInput.restype = None

    xext.XShapeCombineShape.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
    ]
    xext.XShapeCombineShape.restype = None

    xext.XShapeGetRectangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    xext.XShapeGetRectangles.restype = ctypes.POINTER(XRectangle)


@XErrorHandler
def _silent_error_handler(display, error_event):
    # Suppress non-fatal X11 protocol errors (e.g. BadWindow when a transient window closes)
    return 0


x11.XSetErrorHandler(_silent_error_handler)


# --- Helper Functions ---


def get_shape_rectangles(display, xid: int, kind: int):
    """Query XShape rectangles for window. Returns (count, [(x, y, w, h)])."""
    if not xext:
        return 0, []
    count = ctypes.c_int(0)
    ordering = ctypes.c_int(0)
    rects_ptr = xext.XShapeGetRectangles(
        display, xid, kind, ctypes.byref(count), ctypes.byref(ordering)
    )
    n = count.value
    if not rects_ptr or n <= 0:
        return 0, []
    rects = [
        (rects_ptr[i].x, rects_ptr[i].y, rects_ptr[i].width, rects_ptr[i].height)
        for i in range(n)
    ]
    x11.XFree(rects_ptr)
    return n, rects


def sync_input_shape(display, xid: int, reason: str = "") -> bool:
    """Synchronize ShapeInput to ShapeBounding on xid.

    Returns True if an update was applied, False if already in sync.
    """
    if not xext:
        return False
    n_bound, rects_bound = get_shape_rectangles(display, xid, ShapeBounding)
    n_in, rects_in = get_shape_rectangles(display, xid, ShapeInput)

    # If input shape already matches bounding shape, nothing to do
    if n_bound == n_in and rects_bound == rects_in:
        return False

    # Apply synchronization: ShapeInput = ShapeBounding
    xext.XShapeCombineShape(
        display, xid, ShapeInput, 0, 0, xid, ShapeBounding, ShapeSet
    )
    x11.XFlush(display)

    n_after, _ = get_shape_rectangles(display, xid, ShapeInput)
    tag = f" ({reason})" if reason else ""
    log(
        f"xshape sync: {xid:#x} ShapeInput updated {n_in} -> {n_after} rects "
        f"(bounding={n_bound}){tag}"
    )
    return True


def get_window_identity(display, w: int):
    """Fetch class name and WM_NAME for window w. Frees allocated memory."""
    cls_name = ""
    ch = XCH()
    if x11.XGetClassHint(display, w, ctypes.byref(ch)):
        if ch.res_class:
            cls_name = ctypes.string_at(ch.res_class).decode("utf-8", "replace")
            x11.XFree(ch.res_class)
        if ch.res_name:
            x11.XFree(ch.res_name)

    wm_name = ""
    tp = XTextProp()
    if x11.XGetWMName(display, w, ctypes.byref(tp)):
        if tp.value:
            wm_name = ctypes.string_at(tp.value).decode("utf-8", "replace")
            x11.XFree(tp.value)

    return cls_name, wm_name


# --- Main Loop & Window Scanning ---


def scan_and_sync(
    display,
    root: int,
    atom_net_wm_desktop: int,
    atom_net_wm_window_opacity: int,
    claimed_sticky: set,
    tracked_cat_windows: set,
    has_shape: bool,
):
    """Scan root window tree, set stickiness, and attach input shape synchronization."""
    kids = ctypes.POINTER(ctypes.c_ulong)()
    n = ctypes.c_ulong(0)
    r = ctypes.c_ulong(0)
    p = ctypes.c_ulong(0)

    if not x11.XQueryTree(
        display,
        root,
        ctypes.byref(r),
        ctypes.byref(p),
        ctypes.byref(kids),
        ctypes.byref(n),
    ):
        return

    current_windows = set(kids[i] for i in range(n.value)) if kids else set()

    # Prune closed windows
    claimed_sticky.intersection_update(current_windows)
    tracked_cat_windows.intersection_update(current_windows)

    for i in range(n.value):
        w = kids[i]
        cls_name, name = get_window_identity(display, w)

        if cls_name != "steam_proton" or not name:
            continue

        # Claim virtual desktop stickiness
        if w not in claimed_sticky:
            val = ctypes.c_ulong(0xFFFFFFFF)
            x11.XChangeProperty(
                display,
                w,
                atom_net_wm_desktop,
                CARDINAL,
                32,
                PropModeReplace,
                ctypes.byref(val),
                1,
            )
            claimed_sticky.add(w)
            log(f"sticky: {w:#x} {name!r}")

        # Check for DesktopCatInput window
        if has_shape and (name == "DesktopCatInput" or name.startswith("DesktopCatInput")):
            # Force 100% transparency in composite manager (eliminates solid white silhouette)
            val_op = ctypes.c_ulong(0)
            x11.XChangeProperty(
                display,
                w,
                atom_net_wm_window_opacity,
                CARDINAL,
                32,
                PropModeReplace,
                ctypes.byref(val_op),
                1,
            )
            if w not in tracked_cat_windows:
                xext.XShapeSelectInput(display, w, ShapeNotifyMask)
                tracked_cat_windows.add(w)
                log(f"tracking input shape: {w:#x} {name!r}")
            # Ensure shape is in sync
            sync_input_shape(display, w, reason="window scan")

    if kids:
        x11.XFree(kids)

    # Periodic assertion for all tracked DesktopCatInput windows
    if has_shape:
        for w in list(tracked_cat_windows):
            sync_input_shape(display, w, reason="periodic check")

    x11.XFlush(display)


def main(once: bool = False):
    # Ensure kernel delivers SIGTERM if parent launcher terminates
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass

    running = True

    def _sig_handler(signum, frame):
        nonlocal running
        log(f"Caught signal {signum}, terminating gracefully.")
        running = False

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    display_str = os.environ.get("DISPLAY", ":0")
    d = x11.XOpenDisplay(display_str.encode("utf-8"))
    if not d:
        log(f"Failed to open X display {display_str}")
        sys.exit(1)

    log(f"sticky_daemon started on {display_str} (once={once})")

    root = x11.XDefaultRootWindow(d)
    atom_net_wm_desktop = x11.XInternAtom(d, b"_NET_WM_DESKTOP", 0)
    atom_net_wm_window_opacity = x11.XInternAtom(d, b"_NET_WM_WINDOW_OPACITY", 0)

    # Query XShape Extension
    has_shape = False
    shape_event_base = -1
    if xext:
        event_base = ctypes.c_int(0)
        error_base = ctypes.c_int(0)
        if xext.XShapeQueryExtension(
            d, ctypes.byref(event_base), ctypes.byref(error_base)
        ):
            has_shape = True
            shape_event_base = event_base.value
            log(f"XShape extension active (event_base={shape_event_base})")
        else:
            log("XShape extension not supported by X server")
    else:
        log("libXext not available; XShape disabled")

    claimed_sticky = set()
    tracked_cat_windows = set()
    xfd = x11.XConnectionNumber(d)
    ev = XEvent()

    try:
        # Initial scan
        scan_and_sync(
            d,
            root,
            atom_net_wm_desktop,
            atom_net_wm_window_opacity,
            claimed_sticky,
            tracked_cat_windows,
            has_shape,
        )
        if once:
            return

        last_scan_time = time.time()

        while running:
            # Drain and process pending X11 events
            while x11.XPending(d):
                x11.XNextEvent(d, ctypes.byref(ev))
                if has_shape and shape_event_base >= 0:
                    if ev.type == shape_event_base + ShapeNotify:
                        sev = ev.xshape
                        if sev.window in tracked_cat_windows:
                            # Re-sync if Wine updated ShapeBounding, or reset ShapeInput to None
                            if sev.kind == ShapeBounding or (
                                sev.kind == ShapeInput and not sev.shaped
                            ):
                                sync_input_shape(
                                    d,
                                    sev.window,
                                    reason=f"ShapeNotify kind={sev.kind} shaped={sev.shaped}",
                                )

            # Perform periodic tree scan every 1.0 second
            now = time.time()
            if now - last_scan_time >= 1.0:
                scan_and_sync(
                    d,
                    root,
                    atom_net_wm_desktop,
                    atom_net_wm_window_opacity,
                    claimed_sticky,
                    tracked_cat_windows,
                    has_shape,
                )
                last_scan_time = now

            x11.XFlush(d)

            # Wait for socket activity with 1.0s timeout
            try:
                select.select([xfd], [], [], 1.0)
            except (select.error, InterruptedError):
                if not running:
                    break

    finally:
        x11.XCloseDisplay(d)
        log("sticky_daemon stopped.")


if __name__ == "__main__":
    main(once="--once" in sys.argv)

