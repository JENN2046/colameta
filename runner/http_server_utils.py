from __future__ import annotations

import socket
import time
from collections.abc import Callable
from http.server import ThreadingHTTPServer


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server tuned for fast Runner restart loops."""

    # Allow rebinding immediately after a previous Runner HTTP process exits.
    allow_reuse_address = True
    # Do not let in-flight handler threads hold process shutdown or socket close.
    daemon_threads = True
    # Python 3.7+ ThreadingMixIn otherwise waits for non-daemon threads on close.
    block_on_close = False


def is_tcp_port_bindable(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def wait_for_tcp_port_bindable(
    host: str,
    port: int,
    *,
    timeout_seconds: float = 2.0,
    poll_interval_seconds: float = 0.1,
    on_wait: Callable[[float], None] | None = None,
) -> bool:
    if is_tcp_port_bindable(host, port):
        return True
    if on_wait is not None:
        on_wait(timeout_seconds)
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        time.sleep(max(poll_interval_seconds, 0.01))
        if is_tcp_port_bindable(host, port):
            return True
    return is_tcp_port_bindable(host, port)
