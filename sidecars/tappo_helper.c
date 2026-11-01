#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

static BOOL CALLBACK EnumChildProc(HWND child, LPARAM lp) {
    RECT cr;
    if (GetWindowRect(child, &cr)) {
        int cw = cr.right - cr.left;
        int ch = cr.bottom - cr.top;
        if (cw > 10 && ch > 10) {
            SetWindowPos(child, NULL, 0, 0, cw - 2, ch - 2, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
            Sleep(40);
            SetWindowPos(child, NULL, 0, 0, cw, ch, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
        }
    }
    return TRUE;
}

static void nudge(HWND h) {
    RECT r;
    if (!GetWindowRect(h, &r)) return;
    int w = r.right - r.left;
    int h_px = r.bottom - r.top;
    if (w <= 0 || h_px <= 0) return;

    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);

    if (w >= sw && h_px >= sh) {
        // Fullscreen overlay: nudge child webviews directly without resizing top-level
        SetWindowPos(h, NULL, r.left + 1, r.top, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
        Sleep(60);
        SetWindowPos(h, NULL, r.left, r.top, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
        EnumChildWindows(h, EnumChildProc, 0);
    } else {
        // Dialog windows: micro delta to trigger initial swapchain present
        SetWindowPos(h, NULL, r.left, r.top, w + 4, h_px + 4, SWP_NOZORDER | SWP_NOACTIVATE);
        Sleep(60);
        SetWindowPos(h, NULL, r.left, r.top, w, h_px, SWP_NOZORDER | SWP_NOACTIVATE);
    }
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

static DWORD WINAPI NudgeThread(LPVOID lpParam) {
    while (1) {
        EnumWindows(EnumProc, 0);
        Sleep(500);
    }
    return 0;
}

static void send_key(WORD vk, WORD scan, BOOL extended, BOOL down) {
    INPUT input = {0};
    if (!vk) vk = (WORD)MapVirtualKeyW(scan | (extended ? 0xe000 : 0), MAPVK_VSC_TO_VK_EX);
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = vk;
    input.ki.wScan = scan;
    input.ki.dwFlags = (extended ? KEYEVENTF_EXTENDEDKEY : 0) | (down ? 0 : KEYEVENTF_KEYUP);
    input.ki.time = GetTickCount();
    SendInput(1, &input, sizeof(input));
}

static void move_cursor(int root_x, int root_y) {
    int x = root_x + GetSystemMetrics(SM_XVIRTUALSCREEN);
    int y = root_y + GetSystemMetrics(SM_YVIRTUALSCREEN);
    SetCursorPos(x, y);
}

int main(int argc, char **argv) {
    // High-DPI awareness for accurate coordinate matching
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);

    // Launch background window watcher / nudge thread
    HANDLE hThread = CreateThread(NULL, 0, NudgeThread, NULL, 0, NULL);
    if (hThread) CloseHandle(hThread);

    // Read commands from stdin (piped from Linux host bridge)
    char line[128];
    while (fgets(line, sizeof(line), stdin)) {
        unsigned int vk, scan, extended, down;
        int x, y;
        if (sscanf(line, "key %x %x %u %u", &vk, &scan, &extended, &down) == 4) {
            send_key((WORD)vk, (WORD)scan, extended != 0, down != 0);
        } else if (sscanf(line, "move %d %d", &x, &y) == 2) {
            move_cursor(x, y);
        } else if (strncmp(line, "exit", 4) == 0) {
            break;
        }
    }
    return 0;
}
