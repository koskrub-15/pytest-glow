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
        self.life: dict[str, Any] = dict(data.get("life", {}))  # totals since glow first ran here

    @property
    def xp(self) -> int:
        return int(self.life.get("xp", 0))

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

    def last_pass(self, nodeid: str) -> tuple[int, str | None] | None:
        """When the test last passed, and at which commit if git knew."""
        p = self.tests.get(nodeid, {}).get("p")
        if not p:
            return None
        return int(p[0]), (p[1] if len(p) > 1 else None)

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

    def last_green(self) -> dict | None:
        """The last green run that knows its git commit."""
        for run in reversed(self.runs):
            if run.get("ok") and run.get("g"):
                return run
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
        commit: str | None = None,
    ) -> None:
        """``commit``: HEAD as the run saw it; the run keeps it when green, each passing test either way."""
        now = round(time.time())
        for nodeid, (category, dur) in results.items():
            entry = self.tests.pop(nodeid, None) or {"o": "", "d": []}
            entry["o"] = (entry.get("o", "") + CODES.get(category, "?"))[-MAX_OUTCOMES:]
            if category in ("passed", "failed"):
                entry["d"] = [*entry.get("d", []), round(dur, 4)][-MAX_DURATIONS:]
            if category == "passed":
                entry["p"] = [now, commit] if commit else [now]
            # Re-inserting keeps the dict ordered by recency, so the oldest go first.
            self.tests[nodeid] = entry
        while len(self.tests) > MAX_TESTS:
            self.tests.pop(next(iter(self.tests)))
        run = {"t": now, "d": round(duration, 3), "n": len(results), "f": failed, "ok": ok}
        self.greens = self.greens + 1 if ok else 0
        if ok:
            key = str(len(results))
            self.best[key] = round(min(duration, self.best.get(key, duration)), 3)
        if ok and commit:
            run["g"] = commit
        if coverage is not None:
            run["c"] = round(coverage[0], 3)
            self.coverage.update({path: round(pct, 2) for path, pct in coverage[1].items()})
        self.runs.append(run)
        self.runs = self.runs[-MAX_RUNS:]

    def tally(
        self,
        *,
        ok: bool,
        counts: dict[str, int],
        duration: float,
        hour: int,
        xp: int,
        max_combo: int,
        fixed: int,
        shiny: bool,
        boss: str | None = None,
        loot: str | None = None,
    ) -> None:
        """Add a run to the lifetime totals. ``boss``: "won" or "lost" when there was a fight."""
        life = self.life
        life.setdefault("since", round(time.time()))

        def add(key: str, n: float) -> None:
            life[key] = life.get(key, 0) + n

        add("runs", 1)
        add("greens", int(ok))
        add("tests", sum(counts.values()))
        add("passed", counts.get("passed", 0))
        add("failed", counts.get("failed", 0) + counts.get("error", 0))
        add("time", round(duration, 2))
        add("xp", xp)
        add("fixed", fixed)
        add("shiny", int(shiny))
        if boss:
            add(f"boss_{boss}", 1)
        life["best_combo"] = max(life.get("best_combo", 0), max_combo)
        life["best_streak"] = max(life.get("best_streak", 0), self.greens)
        hours = list(life.get("hours", [0] * 24))
        hours[hour % 24] += 1
        life["hours"] = hours
        if loot and loot not in life.get("loot", []):
            life["loot"] = [*life.get("loot", []), loot]

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
                    "life": self.life,
                },
            )


def is_flaky(outcomes: str) -> bool:
    """Passed and failed back and forth at least twice."""
    seq = [c in FAILING for c in outcomes if c in FAILING or c == "P"]
    flips = sum(1 for a, b in itertools.pairwise(seq) if a != b)
    return flips >= 2
