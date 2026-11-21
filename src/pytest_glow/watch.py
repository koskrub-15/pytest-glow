"""pytest --glow-watch: rerun on every save, what failed and what you touched first."""

from __future__ import annotations

import contextlib
import os
import select
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.text import Text

from . import render

POLL = 0.4  # seconds between looks at the files
SETTLE = 0.15  # editors save in bursts: wait this long for the rest
SKIP_DIRS = {"__pycache__", "node_modules", "venv", "env", "build", "dist", "site-packages", "htmlcov"}
CONFIG_FILES = {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py"}

Snapshot = dict[str, int]


def scan(root: str) -> Snapshot:
    """mtime of every Python and pytest config file under root."""
    found: Snapshot = {}
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in files:
            if name.endswith(".py") or name in CONFIG_FILES:
                path = os.path.join(here, name)
                with contextlib.suppress(OSError):  # deleted while we looked
                    found[path] = os.stat(path).st_mtime_ns
    return found


def changes(before: Snapshot, after: Snapshot) -> list[str]:
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def child_args(
    args: tuple[str, ...] | list[str], *, failed: bool = False, pattern: str | None = None, debug: bool = False
) -> list[str]:
    """The same pytest command, without the watch and with the likely failures first.

    ``failed``: only what failed last time; ``pattern``: only tests matching ``-k``; ``debug``: into pdb at the
    first failure of what failed last time.
    """
    kept = [a for a in args if a != "--glow-watch"]
    out = [sys.executable, "-m", "pytest", *kept, "--glow-ff"]
    if failed or debug:
        out.append("--lf")
    if pattern:
        out += ["-k", pattern]
    if debug:
        out += ["--pdb", "-x"]
    return out


class Keys:
    """What's typed at the terminal: a key at a time on a tty, a line at a time from a pipe."""

    def __init__(self, stream: Any = None) -> None:
        self.stream = sys.stdin if stream is None else stream
        try:
            self.fd: int | None = self.stream.fileno()
        except (AttributeError, OSError, ValueError):
            self.fd = None
        self.tty = self.fd is not None and os.isatty(self.fd) and os.name != "nt"
        self._saved: Any = None
        self._buffer = b""

    def __enter__(self) -> Keys:
        if self.tty:
            import termios
            import tty

            with contextlib.suppress(termios.error):
                self._saved = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._saved is not None:
            import termios

            with contextlib.suppress(termios.error):
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            self._saved = None

    def _ready(self, timeout: float) -> bool:
        try:
            return bool(select.select([self.fd], [], [], timeout)[0])
        except (OSError, ValueError):
            time.sleep(timeout)
            return False

    def _read(self) -> bytes:
        try:
            return os.read(self.fd, 1024)
        except OSError:
            return b""

    def key(self, timeout: float) -> str | None:
        """A key, if one came within timeout: Enter as "\n", a closed stdin as "q"."""
        if self.fd is None or os.name == "nt":
            time.sleep(timeout)
            return None
        if self.tty:
            if not self._ready(timeout):
                return None
            got = self._read()
            return got[:1].decode(errors="replace").lower() if got else "q"
        while b"\n" not in self._buffer:
            if not self._ready(timeout):
                return None
            got = self._read()
            if not got:
                return "q"  # nobody can type at us any more
            self._buffer += got
        line, self._buffer = self._buffer.split(b"\n", 1)
        text = line.decode(errors="replace").strip().lower()
        return text[:1] or "\n"

    def line(self, prompt: str) -> str:
        """A whole line, typed the usual way."""
        if self.tty:
            self.__exit__()
            try:
                return input(prompt).strip()
            except EOFError:
                return ""
            finally:
                self.__enter__()
        print(prompt, flush=True)
        while b"\n" not in self._buffer:
            got = self._read() if self.fd is not None else b""
            if not got:
                break
            self._buffer += got
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode(errors="replace").strip()


def wait(root: str, before: Snapshot, key: Callable[[float], str | None]) -> tuple[str, list[str], Snapshot]:
    """Until something changes ("changed", files) or a key is typed (that key)."""
    while True:
        typed = key(POLL)
        if typed is not None:
            return typed, [], before
        after = scan(root)
        if after != before:
            time.sleep(SETTLE)
            after = scan(root)
            return "changed", changes(before, after), after


def _footer(snapshot: Snapshot, failed: bool, pattern: str | None) -> Text:
    tail = Text(f"\n👀 watching {len(snapshot)} files · save to rerun", style="dim")
    for key, what in (
        ("enter", "all"),
        ("f", "all tests" if failed else "only failed"),
        ("p", "pattern"),
        ("d", "debug"),
        ("q", "quit"),
    ):
        tail.append(" · ", style="dim")
        tail.append(key, style="bold")
        tail.append(f" {what}", style="dim")
    return tail


def main(args: tuple[str, ...], cwd: str, root: str) -> int:
    console = Console(highlight=False)
    interactive = sys.stdout.isatty()
    snapshot = scan(root)
    code, run, changed = 0, 0, []
    failed, pattern, debug = False, None, False
    with Keys() as keys:
        while True:
            run += 1
            if interactive and run > 1 and not debug:
                console.clear()
            head = Text.assemble(("👀 ", ""), render.gradient_text("glow watch", render.GRADIENTS["glow"]))
            head.append(f" · run {run}", style="dim")
            if debug:
                head.append(" · debugging what failed", style="bold yellow")
            elif failed:
                head.append(" · only failed", style="bold yellow")
            if pattern:
                head.append(" · -k ", style="dim")
                head.append(pattern, style="bold yellow")
            if changed:
                shown = [os.path.relpath(p, cwd) for p in changed[:3]]
                head.append(" · changed ", style="dim")
                head.append(", ".join(shown) + (f" +{len(changed) - 3}" if len(changed) > 3 else ""), style="bold")
            console.print(head)
            env = dict(os.environ, PYTEST_GLOW_CHANGED=os.pathsep.join(changed))
            command = child_args(args, failed=failed, pattern=pattern, debug=debug)
            keys.__exit__()  # the tests get the terminal as it was: pdb, input(), ^C
            try:
                code = subprocess.call(command, cwd=cwd, env=env)
            except KeyboardInterrupt:
                return code
            finally:
                keys.__enter__()
            debug = False
            console.print(_footer(snapshot, failed, pattern))
            while True:
                try:
                    what, changed, snapshot = wait(root, snapshot, keys.key)
                except KeyboardInterrupt:
                    return code
                if what == "q":
                    return code
                if what == "f":  # one mode at a time: only failed, or only a pattern
                    failed, pattern = not failed, None
                elif what == "p":
                    failed, pattern = False, keys.line("pattern (-k), empty for all › ") or None
                elif what == "d":
                    debug = True
                elif what in ("\n", "\r", "a"):
                    failed, pattern = False, None
                elif what != "changed":
                    continue  # a key that means nothing
                break
