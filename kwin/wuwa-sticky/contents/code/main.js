// Keep WuwaTappo (steam_proton) overlay windows on all virtual desktops without borders.
function sticky(w) {
    if (w.resourceClass !== "steam_proton") return;
    const cap = w.caption;
    if (cap.indexOf("Wuwa") === -1 && cap.indexOf("更新") === -1 && cap !== "Toast" && cap !== "DesktopCatInput") return;
    if (!w.onAllDesktops) w.onAllDesktops = true;
    w.noBorder = true;
    w.keepAbove = true;
    // Prevent KWin from treating Wine TOPMOST overlay as a fullscreen window,
    // which would hide it when another window is focused.
    if (w.fullScreen) w.fullScreen = false;
}
workspace.windowList().forEach(sticky);
workspace.windowAdded.connect(sticky);
