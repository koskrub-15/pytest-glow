"""--glow-profile: where a test's time goes, the test itself, your code or libraries, from sampling its stack.

A background thread looks at the test's stack every INTERVAL while the test body runs and counts the
innermost frame that isn't pytest's: in a test file, elsewhere in the project, or in a library. Time in
time.sleep is counted on its own. The counts ride on the report as an attribute, so they come back from xdist
workers too, and stay out of junitxml (unlike user properties).
"""

from __future__ import annotations

import fnmatch
import os
import sys
import sysconfig
import threading
import time
from collections import Counter
from types import CodeType
from typing import Any

import pytest

from .hang import _internal

INTERVAL = 0.005  # seconds between looks at the stack
PROFILE = "glow_profile"  # on each report: {"test": n, "code": n, "lib": n, "libs": {name: n}, "sleep": seconds}
KINDS = ("test", "code", "lib")


def _stdlib_paths() -> tuple[str, ...]:
    paths = {sysconfig.get_paths()[key] for key in ("stdlib", "platstdlib")}
    return tuple(os.path.realpath(p) + os.sep for p in paths)


class Sampler:
    def __init__(self, root: str, test_patterns: list[str]) -> None:
        self.root = os.path.realpath(root) + os.sep
        self.patterns = [*test_patterns, "conftest.py"]
        self.stdlib = _stdlib_paths()
        # file -> (kind, library), None for pytest's own; by file name, as equal code objects can be from two files
        self._kinds: dict[str, tuple[str, str] | None] = {}
        self._thread: threading.Thread | None = None
        self._target: int | None = None  # the thread running the test, while one runs
        self._counts: Counter = Counter()
        self._libs: Counter = Counter()
        self._slept = 0.0
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def classify(self, code: CodeType) -> tuple[str, str] | None:
        filename = code.co_filename
        found = self._kinds.get(filename, ...)
        if found is not ...:
            return found
        path = os.path.realpath(filename) if filename[:1] not in ("<", "") else filename
        parts = path.split(os.sep)
        if _internal(path):
            found = None
        elif "site-packages" in parts or "dist-packages" in parts:
            at = parts.index("site-packages" if "site-packages" in parts else "dist-packages")
            name = parts[at + 1] if len(parts) > at + 1 else "?"
            found = ("lib", name.removesuffix(".py"))
        elif path.startswith(self.stdlib):
            rest = next(path[len(p) :] for p in self.stdlib if path.startswith(p))
            found = ("lib", rest.split(os.sep, 1)[0].removesuffix(".py"))
        elif path.startswith(self.root):
            name = os.path.basename(path)
            found = ("test", "") if any(fnmatch.fnmatch(name, p) for p in self.patterns) else ("code", "")
        elif path.startswith("<frozen importlib"):
            found = ("lib", "imports")
        elif path.startswith("<frozen "):
            found = ("lib", path[len("<frozen ") : -1])
        else:
            found = ("lib", os.path.basename(path).removesuffix(".py") or "?")  # <string>, elsewhere
        self._kinds[filename] = found
        return found

    def sample(self, frame: Any) -> tuple[str, str] | None:
        while frame is not None:
            found = self.classify(frame.f_code)
            if found is not None:
                return found
            frame = frame.f_back
        return None

    def _run(self) -> None:
        while not self._stopped.wait(INTERVAL):
            target = self._target
            if target is None:
                continue
            frame = sys._current_frames().get(target)
            found = self.sample(frame) if frame is not None else None
            if found is None:
                continue
            with self._lock:
                if self._target is not None:
                    self._counts[found[0]] += 1
                    if found[1]:
                        self._libs[found[1]] += 1

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="glow-profile", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def begin(self) -> None:
        self.start()  # not before a test runs here: an xdist controller never needs the thread
        with self._lock:
            self._counts, self._libs, self._slept = Counter(), Counter(), 0.0
            self._target = threading.get_ident()

    def slept(self, seconds: float) -> None:
        if threading.get_ident() == self._target:
            self._slept += seconds

    def end(self) -> dict | None:
        with self._lock:
            self._target = None
            counts, libs, slept = self._counts, self._libs, self._slept
        if not counts and not slept:
            return None
        result = {**{k: counts[k] for k in KINDS}, "libs": dict(libs.most_common(5))}
        if slept:
            result["sleep"] = round(slept, 4)
        return result


class Profiler:
    """The plugin: samples each phase of a test (setup, call, teardown), and hands the counts to its report."""

    def __init__(self, config: pytest.Config) -> None:
        self.sampler = Sampler(str(config.rootpath), list(config.getini("python_files")))
        self._result: dict | None = None
        self._sleep = time.sleep
        sampler, sleep = self.sampler, self._sleep

        def timed_sleep(seconds: float) -> None:
            t0 = time.perf_counter()
            try:
                sleep(seconds)
            finally:
                sampler.slept(time.perf_counter() - t0)

        # code that did `from time import sleep` before this keeps the plain one: the sleep time is at least this
        time.sleep = timed_sleep
        config.add_cleanup(self._restore)

    def _restore(self) -> None:
        time.sleep = self._sleep

    def pytest_sessionfinish(self) -> None:
        self.sampler.stop()

    def _sampled(self):
        self.sampler.begin()
        try:
            return (yield)
        finally:
            self._result = self.sampler.end()

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_setup(self, item: pytest.Item):
        return (yield from self._sampled())

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item: pytest.Item):
        return (yield from self._sampled())

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_teardown(self, item: pytest.Item, nextitem: pytest.Item | None):
        return (yield from self._sampled())

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        result, self._result = self._result, None
        if result is not None:
            setattr(report, PROFILE, result)
        return report


def profile(report: Any) -> dict | None:
    return getattr(report, PROFILE, None)


def split(seconds: float, counts: dict) -> dict[str, float]:
    """``seconds`` split by the sample counts: {"test": s, "code": s, "lib": s}."""
    total = sum(counts.get(k, 0) for k in KINDS)
    return {k: seconds * counts.get(k, 0) / total if total else 0.0 for k in KINDS}
