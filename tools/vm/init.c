/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Minimal Linux userspace for boot tests: report that userspace runs, show
 * the kernel and CPU identity, then power off. Built as a static aarch64 Linux
 * binary with the pinned Zig toolchain (musl). Output goes to /dev/kmsg, so it
 * appears on the kernel console even without a tty driver.
 */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/utsname.h>
#include <unistd.h>

static void say(const char *text) {
    char line[256];
    int n = snprintf(line, sizeof line, "PROJECT-INIT: %s\n", text);
    int fd = open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        write(fd, line, (size_t)n);
        close(fd);
    }
}

int main(void) {
    char buf[256];
    struct utsname u;
    say("userspace is running (pid 1)");
    if (uname(&u) == 0) {
        snprintf(buf, sizeof buf, "kernel %s %s on %s", u.sysname, u.release, u.machine);
        say(buf);
    }
    if (mount("proc", "/proc", "proc", 0, NULL) == 0) {
        FILE *f = fopen("/proc/cpuinfo", "r");
        while (f && fgets(buf, sizeof buf, f)) {
            if (!strncmp(buf, "CPU implementer", 15) || !strncmp(buf, "CPU part", 8)) {
                buf[strcspn(buf, "\n")] = 0;
                say(buf);
            }
        }
        if (f) fclose(f);
    }
    say("powering off");
    sync();
    reboot(RB_POWER_OFF);
    for (;;) pause();
}
