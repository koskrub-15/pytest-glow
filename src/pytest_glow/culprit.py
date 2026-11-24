"""pytest --glow-bisect TEST: the commit that broke a test, found by running it on the commits in between.

Glow remembers the commit each test last passed at; from there to HEAD it's a binary search, run in a git
worktree of its own: the checkout you work in, uncommitted changes and all, is never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable

from rich.console import Console
from rich.text import Text

from . import render
from .blame import _git, ago
from .history import History

STEP_TIMEOUT = 600  # seconds one run of the test may take
GOOD, BAD, SKIP = "good", "bad", "skip"


class Trouble(Exception):
    """Why it can't bisect, said to the user as is."""


def first_bad(commits: list[str], verdict: Callable[[str], str]) -> list[str]:
    """The commits that may have broken it, oldest first: one, unless the ones around it can't be told.

    ``commits``: after the last good one, up to one known to be bad, oldest first. ``verdict(commit)``: GOOD,
    BAD or SKIP (the test can't run there: not written yet, or the code doesn't import).
    """
    lo, hi = -1, len(commits) - 1  # lo: good (-1, the commit before them all), hi: bad
    while hi - lo > 1:
        mid = (lo + hi) // 2
        tried = None
        # the middle, or the nearest to it either side that can be told
        for offset in range(hi - lo):
            for m in (mid - offset, mid + offset):
                if lo < m < hi and (said := verdict(commits[m])) != SKIP:
                    tried = m, said
                    break
            if tried:
                break
        if tried is None:
            break  # nothing between lo and hi can be run: any of them
        m, said = tried
        if said == GOOD:
            lo = m
        else:
            hi = m
    return commits[lo + 1 : hi + 1]


def _verdict(code: int) -> str:
    if code == 0:
        return GOOD
    if code in (1, 2):  # failed, or couldn't even be collected: the code doesn't import
        return BAD
    return SKIP  # 4, 5: no such test there yet


class Bisect:
    def __init__(self, rootdir: str, nodeid: str, console: Console) -> None:
        self.rootdir, self.nodeid, self.console = rootdir, nodeid, console
        top = _git(rootdir, "rev-parse", "--show-toplevel")
        if not top:
            raise Trouble("not a git repository: there are no commits to look through")
        self.top = top.strip()
        self.rel = os.path.relpath(os.path.realpath(rootdir), os.path.realpath(self.top))
        self.tree = ""
        self.outputs: dict[str, str] = {}

    def __enter__(self) -> Bisect:
        self.tree = tempfile.mkdtemp(prefix="glow-bisect-")
        if _git(self.top, "worktree", "add", "--detach", "--quiet", self.tree, "HEAD") is None:
            shutil.rmtree(self.tree, ignore_errors=True)
            raise Trouble("couldn't make a git worktree to bisect in")
        return self

    def __exit__(self, *exc: object) -> None:
        _git(self.top, "worktree", "remove", "--force", self.tree)
        shutil.rmtree(self.tree, ignore_errors=True)
        _git(self.top, "worktree", "prune")

    def run(self, commit: str) -> str:
        # the worktree is ours alone: whatever a run left in it goes
        if _git(self.tree, "checkout", "--quiet", "--force", "--detach", commit) is None:
            return SKIP
        here = os.path.join(self.tree, self.rel)
        # the worktree's code, not the checkout's an editable install points at
        paths = [here, os.path.join(here, "src"), self.tree, os.path.join(self.tree, "src")]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([*paths, os.environ.get("PYTHONPATH", "")]))
        env.pop("PYTEST_ADDOPTS", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "pytest", self.nodeid, "-q", "-x", "-o", "addopts="]
        command += ["-p", "no:cacheprovider", "-p", "no:glow", "-p", "no:randomly"]
        try:
            done = subprocess.run(command, cwd=here, env=env, capture_output=True, text=True, timeout=STEP_TIMEOUT)
        except subprocess.TimeoutExpired:
            return SKIP
        self.outputs[commit] = done.stdout
        return _verdict(done.returncode)


def resolve(history: History, wanted: str) -> tuple[str, str | None]:
    """The test's node id and the commit it last passed at, from a name, a part of a node id, or TEST@REV."""
    rev = None
    if "@" in wanted:
        wanted, rev = wanted.rsplit("@", 1)
    if wanted in history.tests:
        found = [wanted]
    else:
        found = [n for n in history.tests if n.endswith("::" + wanted)] or [n for n in history.tests if wanted in n]
    if len(found) > 1:
        shown = ", ".join(found[:4]) + (f" and {len(found) - 4} more" if len(found) > 4 else "")
        raise Trouble(f"{wanted!r} is more than one test: {shown}")
    nodeid = found[0] if found else wanted
    if rev is None:
        passed = history.tests.get(nodeid, {}).get("p", [])
        rev = passed[1] if len(passed) > 1 else None
    if rev is None:
        raise Trouble(
            f"glow doesn't know a commit {nodeid} passed at: say one, as --glow-bisect '{nodeid}@<commit or tag>'"
        )
    return nodeid, rev


def _short(top: str, commit: str) -> str:
    return (_git(top, "rev-parse", "--short", commit) or commit[:9]).strip()


def _crash(output: str) -> str:
    """The FAILED line pytest -q ends with, without the node id."""
    for line in reversed(output.splitlines()):
        if line.startswith(("FAILED ", "ERROR ")):
            return line.split(" - ", 1)[1] if " - " in line else line
    return ""


def main(rootdir: str, cache: object, wanted: str) -> int:
    console = Console(highlight=False)
    try:
        return _main(rootdir, History(cache), wanted, console)
    except Trouble as trouble:
        console.print(Text.assemble(("  ✗ ", "bold red"), (str(trouble), "red")), soft_wrap=True)
        return 4


def _main(rootdir: str, history: History, wanted: str, console: Console) -> int:
    nodeid, good = resolve(history, wanted)
    head = Text.assemble(("  🔎 ", ""), render.gradient_text("glow bisect", render.GRADIENTS["glow"]), "  ")
    head.append_text(render.nodeid_text(nodeid))
    console.print(head)
    with Bisect(rootdir, nodeid, console) as bisect:
        top = bisect.top
        full = _git(top, "rev-parse", "--verify", "--quiet", good + "^{commit}")
        if not full:
            raise Trouble(f"no commit {good!r} here")
        good = full.strip()
        if _git(top, "merge-base", "--is-ancestor", good, "HEAD") is None:
            raise Trouble(f"{_short(top, good)} isn't in the history of HEAD")

        def step(commit: str, what: str = "") -> str:
            started = time.monotonic()
            said = bisect.run(commit)
            icon, style = {GOOD: ("✓", "green"), BAD: ("✗", "bold red"), SKIP: ("·", "dim")}[said]
            line = Text.assemble(f"     {icon} ", (_short(top, commit), style), "  ")
            subject = (_git(top, "show", "-s", "--format=%s", commit) or "").strip()
            line.append(subject[:60], style="dim")
            line.append(f"  {what or said} · {render.fmt_dur(time.monotonic() - started)}", style="dim")
            console.print(line)
            return said

        at_head = step("HEAD", "at HEAD")
        if at_head == GOOD:
            console.print(
                Text("  it passes at HEAD: what breaks it isn't committed yet (git diff)", style="bold yellow")
            )
            return 0
        if at_head == SKIP:
            raise Trouble("it can't run at HEAD: is that the test's name?")
        commits = (_git(top, "rev-list", "--first-parent", "--reverse", f"{good}..HEAD") or "").split()
        if not commits:
            raise Trouble(f"it fails at {_short(top, good)}, where it last passed: something besides the code changed")
        if step(good, "last passed here") != GOOD:
            raise Trouble(f"it doesn't pass at {_short(top, good)} either: something besides the code changed")
        steps = max(len(commits).bit_length() - 1, 1)
        console.print(Text(f"  {len(commits)} commits since · about {steps} more runs", style="dim"))
        verdicts: dict[str, str] = {commits[-1]: BAD}

        def verdict(commit: str) -> str:
            if commit not in verdicts:
                verdicts[commit] = step(commit)
            return verdicts[commit]

        suspects = first_bad(commits, verdict)
    _tell(top, suspects, bisect.outputs, console)
    return 0


def _tell(top: str, suspects: list[str], outputs: dict[str, str], console: Console) -> None:
    console.print()
    if len(suspects) > 1:
        console.print(
            Text(f"  💥 broke in one of {len(suspects)} commits (the test can't run in between):", "bold red")
        )
        for commit in suspects:
            subject = (_git(top, "show", "-s", "--format=%s", commit) or "").strip()
            console.print(Text.assemble("     ", (_short(top, commit), "bold"), "  ", (subject, "dim")))
        return
    commit = suspects[0]
    info = (_git(top, "show", "-s", "--format=%s%x00%an%x00%at", commit) or "").strip().split("\x00")
    subject, author, when = [*info, "", "", "0"][:3]
    line = Text.assemble(("  💥 broke in ", "bold red"), (_short(top, commit), "bold"), "  ", (f"“{subject}”", "bold"))
    line.append(f"  {author} · {ago(time.time() - int(when or 0))}", style="dim")
    console.print(line, soft_wrap=True)
    crash = _crash(outputs.get(commit, ""))
    if crash:
        console.print(Text.assemble("     ", (crash, "red")), soft_wrap=True)
    files = [f for f in (_git(top, "show", "--name-only", "--format=", commit) or "").splitlines() if f]
    if files:
        shown = ", ".join(files[:5]) + (f" +{len(files) - 5}" if len(files) > 5 else "")
        console.print(Text.assemble("     ", ("changed ", "dim"), (shown, "cyan")), soft_wrap=True)
    console.print(Text(f"     git show {_short(top, commit)}", style="dim"))
