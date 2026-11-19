"""Who last touched the line that failed, from git blame. Silent outside a git checkout."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from functools import cache

TIMEOUT = 2.0


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
