"""Run-to-run memory, kept in pytest's own cache (.pytest_cache)."""

from __future__ import annotations

import contextlib
import itertools
import statistics
import time
from typing import Any

KEY = "glow/history"
MAX_RUNS = 30
MAX_OUTCOMES = 12
MAX_DURATIONS = 10
MAX_TESTS = 5000

CODES = {
    "passed": "P",
    "failed": "F",
    "error": "E",
    "skipped": "S",
    "xfailed": "x",
    "xpassed": "X",
}
FAILING = {"F", "E"}


class History:
    def __init__(self, cache: Any) -> None:
        self.cache = cache
        data = None
        if cache is not None:
            try:
                data = cache.get(KEY, None)
            except Exception:
                data = None
        if not isinstance(data, dict):
            data = {}
        self.runs: list[dict] = list(data.get("runs", []))
        self.tests: dict[str, dict] = dict(data.get("tests", {}))
        self.coverage: dict[str, float] = dict(data.get("coverage", {}))
        self.best: dict[str, float] = dict(data.get("best", {}))  # fastest green run, by number of tests
        self.achievements: dict[str, int] = dict(data.get("achievements", {}))  # key -> when unlocked
        self.greens: int = int(data.get("greens", 0))  # green runs in a row, beyond the runs kept

    @property
    def enabled(self) -> bool:
        return self.cache is not None

    def outcomes(self, nodeid: str) -> str:
        return self.tests.get(nodeid, {}).get("o", "")

    def last_outcome(self, nodeid: str) -> str | None:
        o = self.outcomes(nodeid)
        return o[-1] if o else None

    def durations(self, nodeid: str) -> list[float]:
        return list(self.tests.get(nodeid, {}).get("d", []))

    def failing_streak(self, nodeid: str) -> int:
        o = self.outcomes(nodeid)
        return len(o) - len(o.rstrip("FE"))

    def personal_best(self, n_tests: int) -> float | None:
        return self.best.get(str(n_tests))

    def median_duration(self, nodeid: str) -> float | None:
        d = self.tests.get(nodeid, {}).get("d", [])
        return statistics.median(d) if len(d) >= 3 else None

    def green_streak(self) -> int:
        n = 0
        for run in reversed(self.runs):
            if not run.get("ok"):
                break
            n += 1
        return n

    def last_coverage(self) -> float | None:
        for run in reversed(self.runs):
            if "c" in run:
                return run["c"]
        return None

    def last_comparable_run(self, n_tests: int) -> dict | None:
        for run in reversed(self.runs):
            if run.get("n") == n_tests:
                return run
        return None

    def record(
        self,
        results: dict[str, tuple[str, float]],
        duration: float,
        ok: bool,
        failed: int,
        coverage: tuple[float, dict[str, float]] | None = None,
    ) -> None:
        for nodeid, (category, dur) in results.items():
            entry = self.tests.pop(nodeid, None) or {"o": "", "d": []}
            entry["o"] = (entry.get("o", "") + CODES.get(category, "?"))[-MAX_OUTCOMES:]
            if category in ("passed", "failed"):
                entry["d"] = [*entry.get("d", []), round(dur, 4)][-MAX_DURATIONS:]
            # Re-inserting keeps the dict ordered by recency, so the oldest go first.
            self.tests[nodeid] = entry
        while len(self.tests) > MAX_TESTS:
            self.tests.pop(next(iter(self.tests)))
        run = {"t": round(time.time()), "d": round(duration, 3), "n": len(results), "f": failed, "ok": ok}
        self.greens = self.greens + 1 if ok else 0
        if ok:
            key = str(len(results))
            self.best[key] = round(min(duration, self.best.get(key, duration)), 3)
        if coverage is not None:
            run["c"] = round(coverage[0], 3)
            self.coverage.update({path: round(pct, 2) for path, pct in coverage[1].items()})
        self.runs.append(run)
        self.runs = self.runs[-MAX_RUNS:]

    def save(self) -> None:
        if self.cache is None:
            return
        with contextlib.suppress(Exception):
            self.cache.set(
                KEY,
                {
                    "runs": self.runs,
                    "tests": self.tests,
                    "coverage": self.coverage,
                    "best": self.best,
                    "achievements": self.achievements,
                    "greens": self.greens,
                },
            )


def is_flaky(outcomes: str) -> bool:
    """Passed and failed back and forth at least twice."""
    seq = [c in FAILING for c in outcomes if c in FAILING or c == "P"]
    flips = sum(1 for a, b in itertools.pairwise(seq) if a != b)
    return flips >= 2
