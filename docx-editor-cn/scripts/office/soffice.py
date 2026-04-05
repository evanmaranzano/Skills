"""
Helper for running LibreOffice (soffice) headless.

On Linux sandboxes where AF_UNIX sockets may be blocked, an optional LD_PRELOAD
shim is available but **disabled by default** for security reasons (it dynamically
compiles C code and injects it via LD_PRELOAD to hijack socket/syscalls).

Security notes:
  - LD_PRELOAD is a rootkit-class technique; we do NOT enable it automatically.
  - To opt-in on a Linux sandbox where soffice fails, set ALLOW_LD_PRELOAD_SHIM=1.
  - The shim C source is auditable (embedded below) and contains no network ops.

Usage:
    from office.soffice import run_soffice, get_soffice_env

    # Option 1 – run soffice directly
    result = run_soffice(["--headless", "--convert-to", "pdf", "input.docx"])

    # Option 2 – get env dict for your own subprocess calls
    env = get_soffice_env()
    subprocess.run(["soffice", ...], env=env)
"""

import logging
import os
import socket
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_SHIM_ENABLED = os.environ.get("ALLOW_LD_PRELOAD_SHIM", "").lower() in ("1", "true", "yes")
_SHIM_SO: Path | None = None  # lazily initialized


def get_soffice_env() -> dict:
    """Return environment dict for running soffice.

    By default only sets SAL_USE_VCLPLUGIN=svp.
    LD_PRELOAD shim is OFF unless ALLOW_LD_PRELOAD_SHIM=1.
    """
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"

    if _SHIM_ENABLED and _needs_shim():
        _ensure_shim()
        if _SHIM_SO is not None:
            env["LD_PRELOAD"] = str(_SHIM_SO)
            logger.warning(
                "LD_PRELOAD shim is active for LibreOffice. "
                "This was explicitly opted in via ALLOW_LD_PRELOAD_SHIM."
            )
    elif _needs_shim() and not _SHIM_ENABLED:
        logger.debug(
            "AF_UNIX sockets appear blocked, but LD_PRELOAD shim is not enabled. "
            "Set ALLOW_LD_PRELOAD_SHIM=1 to enable (Linux sandbox environments only)."
        )

    return env


def run_soffice(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run soffice with the configured environment."""
    env = get_soffice_env()
    return subprocess.run(["soffice"] + args, env=env, **kwargs)


# ─── Linux sandbox shim (optional, opt-in via ALLOW_LD_PRELOAD_SHIM=1) ────────
# This shim replaces AF_UNIX socket calls with AF_UNIX socketpair() calls.
# It is needed ONLY in restricted environments (e.g., Snap/Flatpak sandboxes)
# where Unix domain sockets are blocked. Regular installs do NOT need this.

_SHIM_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

static int (*real_socket)(int, int, int);
static int (*real_socketpair)(int, int, int, int[2]);
static int (*real_listen)(int, int);
static int (*real_accept)(int, struct sockaddr *, socklen_t *);
static int (*real_close)(int);
static int (*real_read)(int, void *, size_t);

static int is_shimmed[1024];
static int peer_of[1024];
static int wake_r[1024];
static int wake_w[1024];
static int listener_fd = -1;

__attribute__((constructor))
static void init(void) {
    real_socket     = dlsym(RTLD_NEXT, "socket");
    real_socketpair = dlsym(RTLD_NEXT, "socketpair");
    real_listen     = dlsym(RTLD_NEXT, "listen");
    real_accept     = dlsym(RTLD_NEXT, "accept");
    real_close      = dlsym(RTLD_NEXT, "close");
    real_read       = dlsym(RTLD_NEXT, "read");
    for (int i = 0; i < 1024; i++) {
        peer_of[i] = -1;
        wake_r[i]  = -1;
        wake_w[i]  = -1;
    }
}

int socket(int domain, int type, int protocol) {
    if (domain == AF_UNIX) {
        int fd = real_socket(domain, type, protocol);
        if (fd >= 0) return fd;
        int sv[2];
        if (real_socketpair(domain, type, protocol, sv) == 0) {
            if (sv[0] >= 0 && sv[0] < 1024) {
                is_shimmed[sv[0]] = 1;
                peer_of[sv[0]]    = sv[1];
                int wp[2];
                if (pipe(wp) == 0) {
                    wake_r[sv[0]] = wp[0];
                    wake_w[sv[0]] = wp[1];
                }
            }
            return sv[0];
        }
        errno = EPERM;
        return -1;
    }
    return real_socket(domain, type, protocol);
}

int listen(int sockfd, int backlog) {
    if (sockfd >= 0 && sockfd < 1024 && is_shimmed[sockfd]) {
        listener_fd = sockfd;
        return 0;
    }
    return real_listen(sockfd, backlog);
}

int accept(int sockfd, struct sockaddr *addr, socklen_t *addrlen) {
    if (sockfd >= 0 && sockfd < 1024 && is_shimmed[sockfd]) {
        if (wake_r[sockfd] >= 0) {
            char buf;
            real_read(wake_r[sockfd], &buf, 1);
        }
        errno = ECONNABORTED;
        return -1;
    }
    return real_accept(sockfd, addr, addrlen);
}

int close(int fd) {
    if (fd >= 0 && fd < 1024 && is_shimmed[fd]) {
        int was_listener = (fd == listener_fd);
        is_shimmed[fd] = 0;
        if (wake_w[fd] >= 0) {
            char c = 0;
            write(wake_w[fd], &c, 1);
            real_close(wake_w[fd]);
            wake_w[fd] = -1;
        }
        if (wake_r[fd] >= 0) { real_close(wake_r[fd]); wake_r[fd]  = -1; }
        if (peer_of[fd] >= 0) { real_close(peer_of[fd]); peer_of[fd] = -1; }
        if (was_listener)
            _exit(0);
    }
    return real_close(fd);
}
"""


def _needs_shim() -> bool:
    """Check if AF_UNIX sockets are blocked."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.close()
        return False
    except OSError:
        return True


def _ensure_shim() -> None:
    """Compile the LD_PRELOAD shim .so from embedded C source (Linux only)."""
    global _SHIM_SO
    tmp_dir = Path(tempfile.gettempdir())
    shim_so = tmp_dir / "lo_socket_shim.so"
    if shim_so.exists():
        _SHIM_SO = shim_so
        return

    src = tmp_dir / "lo_socket_shim.c"
    src.write_text(_SHIM_SOURCE)
    try:
        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-o", str(shim_so), str(src), "-ldl"],
            check=True,
            capture_output=True,
        )
        _SHIM_SO = shim_so
        logger.info("Compiled LD_PRELOAD shim to %s", shim_so)
    finally:
        # Always clean up the source file, even if compilation fails
        if src.exists():
            src.unlink()


if __name__ == "__main__":
    import sys
    result = run_soffice(sys.argv[1:])
    sys.exit(result.returncode)
