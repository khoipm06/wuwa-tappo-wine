#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define MAX_SEEN 128
static HWND seen_hwnds[MAX_SEEN];
static int seen_count = 0;

static int is_seen(HWND h) {
    for (int i = 0; i < seen_count; i++) {
        if (seen_hwnds[i] == h) return 1;
    }
    return 0;
}

static void add_seen(HWND h) {
    if (seen_count < MAX_SEEN) {
        seen_hwnds[seen_count++] = h;
    }
}

static void nudge(HWND h) {
    RECT r;
    if (!GetWindowRect(h, &r)) return;
    int w = r.right - r.left;
    int h_px = r.bottom - r.top;
    if (w <= 0 || h_px <= 0) return;

    SetWindowPos(h, NULL, r.left, r.top, w + 4, h_px + 4, SWP_NOZORDER | SWP_NOACTIVATE);
    Sleep(50);
    SetWindowPos(h, NULL, r.left, r.top, w, h_px, SWP_NOZORDER | SWP_NOACTIVATE);
}

static BOOL CALLBACK EnumProc(HWND h, LPARAM lp) {
    if (!IsWindowVisible(h)) return TRUE;
    char cls[128];
    if (GetClassNameA(h, cls, sizeof(cls))) {
        if (lstrcmpA(cls, "Tauri Window") == 0) {
            if (!is_seen(h)) {
                add_seen(h);
                nudge(h);
            }
        }
    }
    return TRUE;
}

int WINAPI WinMain(HINSTANCE hInst, HINSTANCE hPrev, LPSTR lpCmd, int nShow) {
    int empty_cycles = 0;
    int has_seen_any = 0;

    while (1) {
        EnumWindows(EnumProc, 0);

        if (seen_count > 0) has_seen_any = 1;

        if (has_seen_any) {
            HWND any = FindWindowA("Tauri Window", NULL);
            if (!any) {
                empty_cycles++;
                if (empty_cycles >= 10) break;
            } else {
                empty_cycles = 0;
            }
        }

        Sleep(500);
    }
    return 0;
}
