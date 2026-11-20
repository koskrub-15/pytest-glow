"""pytest --glow-watch: rerun on every save, what failed and what you touched first."""

from __future__ import annotations

import contextlib
import os
import select
import subprocess
import sys
import time
from collections.abc import Callable

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


def child_args(args: tuple[str, ...] | list[str]) -> list[str]:
    """The same pytest command, without the watch and with the likely failures first."""
    kept = [a for a in args if a != "--glow-watch"]
    return [sys.executable, "-m", "pytest", *kept, "--glow-ff"]


def _typed(timeout: float) -> str | None:
    """A line typed at the terminal, if one came within timeout."""
    if os.name == "nt" or sys.stdin is None or sys.stdin.closed:
        time.sleep(timeout)
        return None
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (OSError, ValueError):
        time.sleep(timeout)
        return None
    if not ready:
        return None
    line = sys.stdin.readline()
    return line if line else "q"  # stdin closed: nobody can rerun us any more


def wait(root: str, before: Snapshot, typed: Callable[[float], str | None] = _typed) -> tuple[str, list[str], Snapshot]:
    """Until something changes ("changed", files) or a key is typed ("all" for Enter, "quit" for q)."""
    while True:
        line = typed(POLL)
        if line is not None:
            if line.strip().lower() in ("q", "quit", "exit"):
                return "quit", [], before
            return "all", [], scan(root)
        after = scan(root)
        if after != before:
            time.sleep(SETTLE)
            after = scan(root)
            return "changed", changes(before, after), after


def main(args: tuple[str, ...], cwd: str, root: str) -> int:
    console = Console(highlight=False)
    interactive = sys.stdout.isatty()
    snapshot = scan(root)
    code, run, changed = 0, 0, []
    while True:
        run += 1
        if interactive and run > 1:
            console.clear()
        head = Text.assemble(("👀 ", ""), render.gradient_text("glow watch", render.GRADIENTS["glow"]))
        head.append(f" · run {run}", style="dim")
        if changed:
            shown = [os.path.relpath(p, cwd) for p in changed[:3]]
            head.append(" · changed ", style="dim")
            head.append(", ".join(shown) + (f" +{len(changed) - 3}" if len(changed) > 3 else ""), style="bold")
        console.print(head)
        env = dict(os.environ, PYTEST_GLOW_CHANGED=os.pathsep.join(changed))
        try:
            code = subprocess.call(child_args(args), cwd=cwd, env=env)
        except KeyboardInterrupt:
            return code
        tail = Text(f"\n👀 watching {len(snapshot)} files", style="dim")
        tail.append(" · save to rerun · ", style="dim")
        tail.append("enter", style="bold")
        tail.append(" runs all again · ", style="dim")
        tail.append("q", style="bold")
        tail.append(" quits", style="dim")
        console.print(tail)
        try:
            what, changed, snapshot = wait(root, snapshot)
        except KeyboardInterrupt:
            return code
        if what == "quit":
            return code
