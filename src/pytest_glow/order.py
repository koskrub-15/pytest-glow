"""--glow-ff: run first what most likely fails: what failed last time, what you're editing, new and flaky tests."""

from __future__ import annotations

import os
from collections import Counter
from typing import Any

from . import render
from .blame import _git, _noise
from .history import FAILING, History, is_flaky

# the order groups run in, and how the header calls them
GROUPS = ("failing", "changed", "new", "flaky")


def changed_files(root: str) -> set[str]:
    """Files under root that differ from HEAD (and new ones), relative to root, plus PYTEST_GLOW_CHANGED."""
    found = set()
    tracked = _git(root, "diff", "--name-only", "--relative", "HEAD")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    for path in [*(tracked or "").splitlines(), *(untracked or "").splitlines()]:
        if path and not _noise(path):
            found.add(path)
    for path in os.environ.get("PYTEST_GLOW_CHANGED", "").split(os.pathsep):
        if path:
            found.add(os.path.relpath(os.path.abspath(path), root).replace(os.sep, "/"))
    return found


def _touched(test_file: str, changed: set[str], stems: set[str]) -> bool:
    """The test file changed, or it's named after a module that did (test_cart.py for shop/cart.py)."""
    if test_file in changed:
        return True
    name = os.path.splitext(os.path.basename(test_file))[0]
    return name.removeprefix("test_").removesuffix("_test") in stems


def group_of(nodeid: str, history: History, changed: set[str], stems: set[str]) -> str | None:
    outcomes = history.outcomes(nodeid)
    if outcomes and outcomes[-1] in FAILING:
        return "failing"
    if _touched(render.file_of(nodeid), changed, stems):
        return "changed"
    if history.runs and not outcomes:
        return "new"
    if is_flaky(outcomes):
        return "flaky"
    return None


def reorder(items: list[Any], history: History, root: str) -> Counter:
    """Sort items in place, the likely failures first; the rest keep their order. Returns how many per group."""
    changed = changed_files(root)
    stems = {
        os.path.splitext(os.path.basename(p))[0]
        for p in changed
        if p.endswith(".py") and "test" not in p.split("/")[-1]
    }
    stems.discard("__init__")
    groups = {item.nodeid: group_of(item.nodeid, history, changed, stems) for item in items}
    rank = {name: i for i, name in enumerate(GROUPS)}
    items.sort(key=lambda item: rank.get(groups[item.nodeid], len(GROUPS)))
    return Counter(g for g in groups.values() if g)
