// Keep WuwaTappo (steam_proton) overlay windows on all virtual desktops without borders.
function sticky(w) {
    if (w.resourceClass !== "steam_proton") return;
    const cap = w.caption;
    if (cap.indexOf("Wuwa") === -1 && cap.indexOf("更新") === -1 && cap !== "Toast" && cap !== "DesktopCatInput") return;
    if (!w.onAllDesktops) w.onAllDesktops = true;
    w.noBorder = true;
    w.keepAbove = true;
}
workspace.windowList().forEach(sticky);
workspace.windowAdded.connect(sticky);
