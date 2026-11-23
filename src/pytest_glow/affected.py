"""--glow-affected: run only the tests that what you changed can affect.

While tests run with the flag, sys.monitoring (Python 3.12+) notes which of the project's files each test runs
code from, the code of the wider-scoped fixtures it uses included. The next run picks the tests whose files
changed since they last ran, new tests and the ones that failed; when it can't tell who uses a changed file,
it runs everything. Python files only: a test reading a changed JSON file isn't picked for it.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pytest

from .blame import _git, _noise

KEY = "glow/affected"
REPORT_ATTR = "glow_deps"  # on the teardown report: the project files the test ran code from
TOOL_IDS = (4, 3)  # sys.monitoring tool ids nobody standard claims (debugger 0, coverage 1, profiler 2, optimizer 5)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "site-packages", ".tox", ".nox", "build"}


def supported() -> bool:
    return hasattr(sys, "monitoring")


def _python_files(root: str) -> list[str]:
    """The project's Python files, relative to root with / separators: git's view when there's git."""
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py")
    if listed is not None:
        return [p for p in listed.splitlines() if p and not _noise(p) and os.path.isfile(os.path.join(root, p))]
    found = []
    for here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        rel = os.path.relpath(here, root)
        for name in files:
            if name.endswith(".py"):
                found.append(name if rel == "." else f"{rel}/{name}".replace(os.sep, "/"))
    return found


def snapshot(root: str, before: dict) -> dict[str, list]:
    """path -> [mtime_ns, size, hash] of every Python file; a file unchanged on disk keeps its hash unread."""
    files = {}
    for path in _python_files(root):
        try:
            st = os.stat(os.path.join(root, path))
            old = before.get(path)
            if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
                files[path] = old
                continue
            with open(os.path.join(root, path), "rb") as f:
                digest = hashlib.blake2b(f.read(), digest_size=6).hexdigest()
        except OSError:
            continue
        files[path] = [st.st_mtime_ns, st.st_size, digest]
    return files


@dataclass
class Choice:
    selected: list = field(default_factory=list)
    deselected: list = field(default_factory=list)
    why: Counter = field(default_factory=Counter)  # changed / new / failing -> how many tests
    changed: list[str] = field(default_factory=list)  # the files that changed since the tests last ran
    everything: str | None = None  # why it runs everything, when it does


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def changed_since(stored: dict, files: dict) -> set[str]:
    """The Python files that changed, or went, since the map last saw them."""
    known: dict = stored.get("files", {})
    now = {path: entry[2] for path, entry in files.items()}
    return {p for p in now if p in known and known[p][2] != now[p]} | {p for p in known if p not in now}


def choose(items: list, stored: dict, files: dict, failing: set[str], rootdir_of: Any) -> Choice:
    """Which items to run, given the stored map, the files as they are now and what failed last time.
    ``rootdir_of(item)`` is the item's path relative to the root."""
    tests: dict = stored.get("tests", {})
    known: dict = stored.get("files", {})
    failing = failing | set(stored.get("failed", ()))
    choice = Choice()
    if not tests:
        choice.selected, choice.everything = list(items), "first run: learning which tests use which files"
        return choice
    now = {path: entry[2] for path, entry in files.items()}
    changed = changed_since(stored, files)
    claimed = {p for deps in tests.values() for p in deps}
    conftests = {_parent(p) for p in changed | (now.keys() - known.keys()) if p.rsplit("/", 1)[-1] == "conftest.py"}
    unclaimed = sorted(p for p in changed if p not in claimed and p.rsplit("/", 1)[-1] != "conftest.py")
    choice.changed = sorted(changed)
    if unclaimed:
        choice.selected = list(items)
        choice.everything = f"no test ran code from {unclaimed[0]}, so can't tell what it affects"
        return choice
    for item in items:
        deps = tests.get(item.nodeid)
        path = rootdir_of(item)
        if deps is None:
            reason = "new"
        elif item.nodeid in failing:
            reason = "failing"
        elif any(now.get(p) != h for p, h in deps.items()) or any(not d or path.startswith(d + "/") for d in conftests):
            reason = "changed"
        else:
            choice.deselected.append(item)
            continue
        choice.why[reason] += 1
        choice.selected.append(item)
    return choice


class Tracker:
    """Where tests run (in-process, or an xdist worker): which project files each test runs code from."""

    def __init__(self, root: str) -> None:
        self.root = os.path.realpath(root) + os.sep
        self.tool: int | None = None
        self._mine: dict[str, str | None] = {}  # co_filename -> path relative to the root, None if not ours
        self._open: list[set] = []  # the sets the code running now counts for: the test's, a fixture's
        self._test: set[str] = set()
        self._fixtures: dict[str, set[str]] = {}  # wider-scoped fixture -> the files its setup ran

    def start(self) -> bool:
        mon = sys.monitoring
        for tool in TOOL_IDS:
            try:
                mon.use_tool_id(tool, "pytest-glow")
            except ValueError:
                continue
            self.tool = tool
            mon.register_callback(tool, mon.events.PY_START, self._started)
            mon.set_events(tool, mon.events.PY_START)
            return True
        return False

    def stop(self) -> None:
        if self.tool is not None:
            mon = sys.monitoring
            mon.set_events(self.tool, 0)
            mon.register_callback(self.tool, mon.events.PY_START, None)
            mon.free_tool_id(self.tool)
            self.tool = None

    def _relative(self, filename: str) -> str | None:
        path = os.path.realpath(filename) if filename[:1] not in ("<", "") else ""
        if not path.startswith(self.root) or "site-packages" in path.split(os.sep):
            return None
        return path[len(self.root) :].replace(os.sep, "/")

    def _started(self, code: Any, offset: int) -> Any:
        filename = code.co_filename
        rel = self._mine.get(filename, ...)
        if rel is ...:
            rel = self._mine[filename] = self._relative(filename)
        if rel is not None:
            for found in self._open:
                found.add(rel)
        # not again until the next test: then it counts once more (sys.monitoring.restart_events)
        return sys.monitoring.DISABLE

    def pytest_runtest_logstart(self) -> None:
        self._test = set()
        self._open = [self._test]
        sys.monitoring.restart_events()

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef: Any):
        if fixturedef.scope == "function" or not self._open:
            return (yield)
        # set up once for many tests: what it runs counts for each of them, not only for the first
        found: set[str] = set()
        self._open.append(found)
        sys.monitoring.restart_events()
        try:
            return (yield)
        finally:
            self._open.remove(found)
            self._fixtures[fixturedef.argname] = found

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        if call.when == "teardown":
            deps = set(self._test)
            for name in getattr(item, "fixturenames", ()):
                deps |= self._fixtures.get(name, set())
            setattr(report, REPORT_ATTR, sorted(deps))
            self._open = []
        return report

    def pytest_unconfigure(self) -> None:
        self.stop()


class Keeper:
    """Where the run is reported (in-process, or the xdist controller): keeps the map up to date."""

    def __init__(self, cache: Any, files: dict, stored: dict) -> None:
        self.cache, self.files, self.stored = cache, files, stored
        self._seen: dict[str, list[str]] = {}
        self._failed: set[str] = set()  # kept here too: glow's history isn't, under --no-glow

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.failed:
            self._failed.add(report.nodeid)
        deps = getattr(report, REPORT_ATTR, None)
        if report.when == "teardown" and deps is not None:
            self._seen[report.nodeid] = deps

    def pytest_sessionfinish(self) -> None:
        if not self._seen:
            return
        tests = dict(self.stored.get("tests", {}))
        for nodeid, deps in self._seen.items():
            # the files as they were when the run began: one edited while it ran counts as changed next time
            tests[nodeid] = {p: self.files[p][2] for p in deps if p in self.files}
        known = dict(self.stored.get("files", {}))
        known.update(self.files)
        for path in list(known):
            if path not in self.files:
                del known[path]
        with contextlib.suppress(Exception):  # a read-only cache: the map just isn't kept
            failed = (set(self.stored.get("failed", ())) - self._seen.keys()) | self._failed
            self.cache.set(KEY, {"files": known, "tests": tests, "failed": sorted(failed)})
