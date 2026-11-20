"""On GitHub Actions: the run as a markdown job summary, on the run's page. The log stays plain pytest."""

from __future__ import annotations

import os
import platform
import time
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest

from . import diff as assert_diff
from . import render, rerun
from .reporter import group_failures

MAX_FAILURES = 30
MAX_SLOWEST = 5
_ORDER = ("failed", "error", "passed", "skipped", "xfailed", "xpassed")
_ICONS = {"failed": "❌", "error": "💥", "passed": "✅", "skipped": "⏭️", "xfailed": "🫥", "xpassed": "❗"}


def wanted(config: pytest.Config) -> str | None:
    """The summary file to append to, when there is one and the summary isn't turned off."""
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path or hasattr(config, "workerinput"):
        return None
    if os.environ.get("PYTEST_GLOW_SUMMARY", "").strip().lower() in ("0", "false", "no", "off"):
        return None
    try:
        if config.getini("glow_summary") is False:
            return None
    except ValueError:
        pass
    return path


def _cell(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|").replace("<", "&lt;")


class JobSummary:
    def __init__(self, config: pytest.Config, path: str) -> None:
        self.config, self.path = config, path
        self.counts: Counter = Counter()
        self.failures: list[Any] = []
        self.durations: dict[str, float] = {}
        self.flaky: list[tuple[str, int, str]] = []
        self.explained: dict[tuple[str, str], str] = {}  # what differed in a failed `==`, by (nodeid, when)
        self._compare: tuple[Any, Any] | None = None
        self.start = time.monotonic()

    def pytest_assertrepr_compare(self, op: str, left: Any, right: Any) -> None:
        if op == "==":
            self._compare = (left, right)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        compare, self._compare = self._compare, None
        error = call.excinfo.value if call.excinfo is not None else None
        # only when the failure is that `==`, not one caught earlier by pytest.raises
        if report.failed and compare is not None and isinstance(error, AssertionError) and " == " in str(error):
            found = assert_diff.explain(*compare)
            if found is not None and found.summary:
                self.explained[(report.nodeid, report.when)] = found.summary
        return report

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        category = self.config.hook.pytest_report_teststatus(report=report, config=self.config)[0]
        self.durations[report.nodeid] = self.durations.get(report.nodeid, 0.0) + report.duration
        if report.failed:
            self.failures.append(SimpleNamespace(report=report))
        flaky = rerun.flaky(report) if report.when == "call" and report.passed else None
        if flaky is not None:
            self.flaky.append((report.nodeid, *flaky))
        if category in _ICONS:
            self.counts[category] += 1

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.counts["error"] += 1
            self.failures.append(SimpleNamespace(report=report))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(self.markdown(session, exitstatus))
        except OSError:
            pass

    def _link(self, path: str, line: int | None) -> str | None:
        server, repo, sha = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_SHA"))
        workspace = os.environ.get("GITHUB_WORKSPACE") or str(self.config.rootpath)
        path = os.path.abspath(path)
        if not (server and repo and sha) or not path.startswith(os.path.abspath(workspace) + os.sep):
            return None
        rel = os.path.relpath(path, workspace).replace(os.sep, "/")
        return f"{server}/{repo}/blob/{sha}/{rel}" + (f"#L{line}" if line else "")

    def _where(self, report: Any) -> str:
        crash = getattr(report.longrepr, "reprcrash", None)
        if crash is None:
            return ""
        label = f"{os.path.basename(str(crash.path))}:{crash.lineno}"
        url = self._link(str(crash.path), crash.lineno)
        return f"[{label}]({url})" if url else f"`{label}`"

    def markdown(self, session: pytest.Session, exitstatus: int) -> str:
        duration = time.monotonic() - self.start
        failing = self.counts["failed"] + self.counts["error"]
        named = {k: f"{k}s" if k == "error" and self.counts[k] > 1 else k for k in _ORDER}
        counts = " · ".join(f"{self.counts[k]} {named[k]}" for k in _ORDER if self.counts[k])
        if self.flaky:
            counts += f" · {len(self.flaky)} flaky"
        if failing:
            head = f"### ❌ pytest: {counts or 'failed'}"
        elif exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
            head = "### ⚪ pytest: no tests ran"
        elif exitstatus != pytest.ExitCode.OK:
            head = f"### ⚠️ pytest: exited with {int(exitstatus)} · {counts}"
        elif self.flaky:
            head = f"### 〰️ pytest: green, but flaky · {counts}"
        else:
            head = f"### ✅ pytest: all green · {counts}"
        out = [head, ""]
        versions = f"Python {platform.python_version()} · pytest {pytest.__version__}"
        out += [f"{render.fmt_dur(duration)} · {versions} · `{session.config.rootpath.name}`", ""]

        if self.failures:
            out += ["| | test | where | error |", "|---|---|---|---|"]
            for group in group_failures(self.failures)[:MAX_FAILURES]:
                report = group[0].report
                when = getattr(report, "when", "collect")
                kind = "failed" if when == "call" else "error"
                when = "" if when == "call" else f" ({when})"
                more = f" <sub>+{len(group) - 1} more like this</sub>" if len(group) > 1 else ""
                explained = self.explained.get((report.nodeid, getattr(report, "when", "")))
                message = _cell(explained or render.crash_message(report))
                test = f"`{_cell(report.nodeid, 120)}`{when}{more}"
                out.append(f"| {_ICONS[kind]} | {test} | {self._where(report)} | {message} |")
            groups = len(group_failures(self.failures))
            if groups > MAX_FAILURES:
                out.append(f"\n… and {groups - MAX_FAILURES} more")
            out.append("")

        if self.flaky:
            out += ["| | flaky test | passed on try | first failure |", "|---|---|---|---|"]
            for nodeid, attempts, first in self.flaky[:MAX_FAILURES]:
                out.append(f"| 〰️ | `{_cell(nodeid, 120)}` | {attempts} | {_cell(first)} |")
            out.append("")

        slowest = sorted(self.durations.items(), key=lambda item: -item[1])[:MAX_SLOWEST]
        slowest = [(nodeid, d) for nodeid, d in slowest if d >= 0.1]
        if slowest:
            out += ["<details><summary>Slowest tests</summary>", "", "| | test |", "|---:|---|"]
            out += [f"| {render.fmt_dur(d)} | `{_cell(nodeid, 120)}` |" for nodeid, d in slowest]
            out += ["", "</details>", ""]
        return "\n".join(out) + "\n"
