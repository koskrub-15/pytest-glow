"""--glow-rerun: a failed test runs again; one that passes then is flaky, not broken."""

from __future__ import annotations

import os
from typing import Any

import pytest
from _pytest.runner import runtestprotocol

from . import render

FLAKY = "glow_flaky"  # a user property on the passing report: (attempts it took, how the first one failed)


def reruns(config: pytest.Config) -> int:
    """How many more times a failed test may run: --glow-rerun[=N], PYTEST_GLOW_RERUN=N or glow_rerun = N."""
    value = config.getoption("glow_rerun", None)
    if value is None:
        value = os.environ.get("PYTEST_GLOW_RERUN", "").strip() or None
    if value is None:
        try:
            value = config.getini("glow_rerun") or None
        except ValueError:
            value = None
    try:
        times = int(value) if value is not None else 0
    except ValueError:
        raise pytest.UsageError(f"--glow-rerun takes a number of reruns, not {value!r}") from None
    if config.getoption("usepdb", False) or config.getoption("reruns", 0):  # pdb wants the first failure
        return 0
    return max(times, 0)


def flaky(report: Any) -> tuple[int, str] | None:
    for name, value in getattr(report, "user_properties", ()):
        if name == FLAKY:
            return int(value[0]), str(value[1])
    return None


def protocol(item: pytest.Item, nextitem: pytest.Item | None, times: int) -> bool:
    ihook = item.ihook
    ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    first, attempt = None, 0
    while True:
        attempt += 1
        reports = runtestprotocol(item, nextitem=nextitem, log=False)
        failed = next((r for r in reports if r.when == "call" and r.failed), None)
        if failed is None or attempt > times:
            break
        first = first or failed
    if first is not None and failed is None:
        for report in reports:
            # a new list: the reports share the item's own
            report.user_properties = [*report.user_properties, (FLAKY, (attempt, render.crash_message(first)))]
    for report in reports:
        ihook.pytest_runtest_logreport(report=report)
    ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
