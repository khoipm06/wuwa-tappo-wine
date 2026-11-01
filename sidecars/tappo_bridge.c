#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <dirent.h>
#include <signal.h>
#include <errno.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <linux/input.h>

#define MAX_DEVICES 64
#define MAX_EVENTS 32
#define MAX_STAND_INS 6

typedef struct {
    unsigned char vk;
    unsigned char scan;
    unsigned char ext;
} StandInKey;

// Stand-in virtual keys (F13..F24) so Tappo counts taps without typing text into focused windows
static const StandInKey LEFT_STAND_INS[MAX_STAND_INS] = {
    {0x7C, 0x64, 0}, {0x7E, 0x66, 0}, {0x80, 0x68, 0},
    {0x82, 0x6A, 0}, {0x84, 0x6C, 0}, {0x86, 0x6E, 0}
};

static const StandInKey RIGHT_STAND_INS[MAX_STAND_INS] = {
    {0x7D, 0x65, 0}, {0x7F, 0x67, 0}, {0x81, 0x69, 0},
    {0x83, 0x6B, 0}, {0x85, 0x6D, 0}, {0x87, 0x76, 0}
};

static int left_held[MAX_STAND_INS] = {0};
static int right_held[MAX_STAND_INS] = {0};
static short key_mapping[KEY_MAX + 1] = {0};

static volatile sig_atomic_t g_running = 1;

static void handle_sig(int sig) {
    (void)sig;
    g_running = 0;
}

static int is_left_hand(int code) {
    switch (code) {
        case KEY_ESC:
        case KEY_F1: case KEY_F2: case KEY_F3: case KEY_F4: case KEY_F5: case KEY_F6:
        case KEY_GRAVE:
        case KEY_1: case KEY_2: case KEY_3: case KEY_4: case KEY_5:
        case KEY_TAB:
        case KEY_Q: case KEY_W: case KEY_E: case KEY_R: case KEY_T:
        case KEY_CAPSLOCK:
        case KEY_A: case KEY_S: case KEY_D: case KEY_F: case KEY_G:
        case KEY_LEFTSHIFT:
        case KEY_102ND:
        case KEY_Z: case KEY_X: case KEY_C: case KEY_V: case KEY_B:
        case KEY_LEFTCTRL:
        case KEY_LEFTMETA:
        case KEY_LEFTALT:
            return 1;
        default:
            return 0;
    }
}

static int is_keyboard_device(int fd) {
    unsigned long ev_bits[(EV_MAX + 7) / 8] = {0};
    unsigned long key_bits[(KEY_MAX + 7) / 8] = {0};

    if (ioctl(fd, EVIOCGBIT(0, sizeof(ev_bits)), ev_bits) < 0) return 0;
    if (!(ev_bits[0] & (1 << EV_KEY))) return 0;

    if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(key_bits)), key_bits) < 0) return 0;

    // Check if device supports KEY_A and KEY_SPACE
    int has_a = (key_bits[KEY_A / (8 * sizeof(long))] >> (KEY_A % (8 * sizeof(long)))) & 1;
    int has_space = (key_bits[KEY_SPACE / (8 * sizeof(long))] >> (KEY_SPACE % (8 * sizeof(long)))) & 1;
    return has_a && has_space;
}

static int scan_and_add_keyboards(int epoll_fd, int *fds, int max_fds) {
    DIR *dir = opendir("/dev/input");
    if (!dir) return 0;

    int count = 0;
    struct dirent *ent;
    while ((ent = readdir(dir)) != NULL && count < max_fds) {
        if (strncmp(ent->d_name, "event", 5) != 0) continue;

        char path[512];
        snprintf(path, sizeof(path), "/dev/input/%s", ent->d_name);

        int fd = open(path, O_RDONLY | O_NONBLOCK);
        if (fd < 0) continue;

        char name[128] = {0};
        ioctl(fd, EVIOCGNAME(sizeof(name)), name);
        if (strcasestr(name, "yubico") || strcasestr(name, "yubikey")) {
            close(fd);
            continue;
        }

        if (is_keyboard_device(fd)) {
            struct epoll_event ev;
            ev.events = EPOLLIN;
            ev.data.fd = fd;
            if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, fd, &ev) == 0) {
                fds[count++] = fd;
            } else {
                close(fd);
            }
        } else {
            close(fd);
        }
    }
    closedir(dir);
    return count;
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_sig);
    signal(SIGTERM, handle_sig);

    // Disable stdout buffering for immediate pipe delivery
    setvbuf(stdout, NULL, _IONBF, 0);

    int epoll_fd = epoll_create1(0);
    if (epoll_fd < 0) {
        perror("epoll_create1");
        return 1;
    }

    int fds[MAX_DEVICES];
    int dev_count = scan_and_add_keyboards(epoll_fd, fds, MAX_DEVICES);

    if (dev_count == 0) {
        fprintf(stderr, "[tappo_bridge] No accessible keyboard input devices found in /dev/input.\n");
        fprintf(stderr, "[tappo_bridge] Ensure your user is in the 'input' group: sudo usermod -a -G input $USER\n");
    } else {
        fprintf(stderr, "[tappo_bridge] Monitoring %d keyboard device(s) for global typing...\n", dev_count);
    }

    struct epoll_event events[MAX_EVENTS];
    struct input_event ev_buf[32];

    while (g_running) {
        int nfds = epoll_wait(epoll_fd, events, MAX_EVENTS, 200);
        if (nfds < 0) {
            if (errno == EINTR) continue;
            break;
        }

        for (int i = 0; i < nfds; i++) {
            int fd = events[i].data.fd;
            ssize_t n = read(fd, ev_buf, sizeof(ev_buf));
            if (n <= 0) continue;

            size_t count = n / sizeof(struct input_event);
            for (size_t j = 0; j < count; j++) {
                struct input_event *ev = &ev_buf[j];
                if (ev->type != EV_KEY) continue;
                if (ev->code > KEY_MAX) continue;

                if (ev->value == 1) { // Key down
                    int left = is_left_hand(ev->code);
                    int *held = left ? left_held : right_held;
                    const StandInKey *pool = left ? LEFT_STAND_INS : RIGHT_STAND_INS;

                    // Find unused stand-in key
                    int slot = -1;
                    for (int s = 0; s < MAX_STAND_INS; s++) {
                        if (!held[s]) { slot = s; break; }
                    }
                    if (slot >= 0) {
                        held[slot] = 1;
                        key_mapping[ev->code] = (short)((left ? 1 : 2) << 8 | slot);
                        printf("key %x %x %u 1\n", pool[slot].vk, pool[slot].scan, pool[slot].ext);
                    }
                } else if (ev->value == 0) { // Key up
                    short mapped = key_mapping[ev->code];
                    if (mapped) {
                        int left = (mapped >> 8) == 1;
                        int slot = mapped & 0xFF;
                        if (slot >= 0 && slot < MAX_STAND_INS) {
                            const StandInKey *pool = left ? LEFT_STAND_INS : RIGHT_STAND_INS;
                            int *held = left ? left_held : right_held;
                            held[slot] = 0;
                            printf("key %x %x %u 0\n", pool[slot].vk, pool[slot].scan, pool[slot].ext);
                        }
                        key_mapping[ev->code] = 0;
                    }
                }
            }
        }
    }

    for (int i = 0; i < dev_count; i++) close(fds[i]);
    close(epoll_fd);
    return 0;
}
