"""Tests that talk to the internet: slow, flaky, and they fail on a plane. Which ones, and to where.

socket.socket.connect is wrapped while glow runs; a connection to a loopback or private address (a database
in docker, a local server) doesn't count. Names come from the lookups the test did (getaddrinfo).
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading
from typing import Any

import pytest

REPORT_ATTR = "glow_net"  # on the teardown report: ["host:port", ...] the test connected to


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_multicast)


class Watcher:
    """Where tests run (in-process, or an xdist worker of a glowing run)."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}  # ip -> the host name it was looked up as
        self._seen: dict[str, None] = {}  # this test's, in order
        self._lock = threading.Lock()
        self._active = False
        self._connect = socket.socket.connect
        self._connect_ex = socket.socket.connect_ex
        self._getaddrinfo = socket.getaddrinfo
        watcher = self

        def connect(sock: socket.socket, address: Any) -> Any:
            watcher._saw(sock, address)
            return watcher._connect(sock, address)

        def connect_ex(sock: socket.socket, address: Any) -> Any:
            watcher._saw(sock, address)
            return watcher._connect_ex(sock, address)

        def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
            found = watcher._getaddrinfo(host, *args, **kwargs)
            if isinstance(host, str):
                with contextlib.suppress(Exception):
                    for *_, sockaddr in found:
                        watcher._names[str(sockaddr[0])] = host
            return found

        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo

    def restore(self) -> None:
        socket.socket.connect = self._connect  # type: ignore[method-assign]
        socket.socket.connect_ex = self._connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = self._getaddrinfo

    def _saw(self, sock: socket.socket, address: Any) -> None:
        if not self._active or sock.family not in (socket.AF_INET, socket.AF_INET6):
            return
        try:
            host, port = str(address[0]), int(address[1])
        except (TypeError, ValueError, IndexError):
            return
        if not _public(host):
            return
        with self._lock:
            self._seen[f"{self._names.get(host, host)}:{port}"] = None

    def pytest_runtest_logstart(self) -> None:
        with self._lock:
            self._seen = {}
        self._active = True

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        if call.when == "teardown":
            self._active = False
            with self._lock:
                seen, self._seen = list(self._seen), {}
            if seen:
                setattr(report, REPORT_ATTR, seen)
        return report

    def pytest_unconfigure(self) -> None:
        self.restore()


def of(report: Any) -> list[str]:
    return list(getattr(report, REPORT_ATTR, None) or ())
