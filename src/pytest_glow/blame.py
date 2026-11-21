"""What git knows: who last touched the line that failed, and what changed since a green run.

Everything here is silent (returns None) outside a git checkout or when git is missing or slow.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from functools import cache

TIMEOUT = 2.0
# what tools write while tests run, in case a project doesn't ignore it
_NOISE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", ".tox", ".nox"}


@dataclass
class Blame:
    author: str
    when: int | None  # unix time; None when the line isn't committed yet
    commit: str
    yours: bool


def _git(cwd: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


@cache
def _me(cwd: str) -> str | None:
    name = _git(cwd, "config", "user.name")
    return name.strip() if name else None


def blame(path: str, line: int) -> Blame | None:
    path = os.path.abspath(path)
    cwd = os.path.dirname(path)
    out = _git(cwd, "blame", "--porcelain", "-L", f"{line},{line}", "--", os.path.basename(path))
    if not out:
        # a file git doesn't track yet, inside a checkout, is just as uncommitted
        if (_git(cwd, "rev-parse", "--is-inside-work-tree") or "").strip() == "true":
            return Blame(author=_me(cwd) or "you", when=None, commit="", yours=True)
        return None
    lines = out.splitlines()
    commit = lines[0].split(" ", 1)[0]
    fields = dict(ln.split(" ", 1) for ln in lines[1:] if " " in ln and not ln.startswith("\t"))
    if set(commit) == {"0"}:
        return Blame(author=_me(cwd) or "you", when=None, commit="", yours=True)
    author = fields.get("author", "someone")
    when = int(fields["author-time"]) if fields.get("author-time", "").isdigit() else None
    return Blame(author=author, when=when, commit=commit[:7], yours=author == _me(cwd))


def ago(seconds: float) -> str:
    seconds = max(seconds, 0)  # times are kept to the second, rounded either way
    for unit, size in (("year", 365 * 86400), ("month", 30 * 86400), ("day", 86400), ("hour", 3600), ("minute", 60)):
        n = int(seconds // size)
        if n:
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def describe(b: Blame, now: float | None = None) -> str:
    if b.when is None:
        return "not committed yet — this one's all yours"
    who = "you" if b.yours else b.author
    return f"last touched by {who}, {ago((now or time.time()) - b.when)} · {b.commit}"


def head(cwd: str) -> str | None:
    out = _git(cwd, "rev-parse", "HEAD")
    return out.strip() if out else None


def commits_since(cwd: str, commit: str) -> int | None:
    """How many commits HEAD is ahead of ``commit``."""
    out = _git(cwd, "rev-list", "--count", f"{commit}..HEAD")
    return int(out) if out and out.strip().isdigit() else None


def changed_since(cwd: str, commit: str, since: float) -> list[str] | None:
    """Files under cwd that differ from ``commit`` and were touched after ``since``, newest first.

    The time filter drops edits that were already there, uncommitted, when ``commit`` was green.
    """
    tracked = _git(cwd, "diff", "--name-only", "--relative", commit)
    if tracked is None:
        return None
    untracked = _git(cwd, "ls-files", "--others", "--exclude-standard") or ""
    found: dict[str, float] = {}
    for path in {*tracked.splitlines(), *untracked.splitlines()}:
        if not path or _noise(path):
            continue
        try:
            mtime = os.path.getmtime(os.path.join(cwd, path))
        except OSError:
            mtime = float("inf")  # deleted since
        if mtime > since + 1:  # run times are kept to the second
            found[path] = mtime
    return sorted(found, key=lambda p: found[p], reverse=True)


def _noise(path: str) -> bool:
    parts = path.split("/")
    return bool(_NOISE_DIRS.intersection(parts)) or parts[-1].startswith(".coverage") or path.endswith(".pyc")
