"""Achievements: utterly useless, unlocked once per project and remembered in the history."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    blurb: str


ALL = [
    Achievement("first_blood", "First Blood", "the first red run after a clean record"),
    Achievement("phoenix", "Phoenix", "green again after 5 red runs in a row"),
    Achievement("night_owl", "Night Owl", "running tests between midnight and 5 am"),
    Achievement("minimalist", "Minimalist", "100% coverage of a file with 3 statements or fewer"),
    Achievement("sniper", "Sniper", "coverage lands exactly on --cov-fail-under"),
    Achievement("speedrunner", "Speedrunner", "beat your personal best"),
    Achievement("surgeon", "Surgeon", "fixed a test that had failed 5 runs in a row"),
    Achievement("clean_sweep", "Clean Sweep", "100+ tests, every one passed, not a single warning"),
    Achievement("centurion", "Centurion", "100 green runs in a row"),
    Achievement("friday_deploy", "Friday Deploy", "green on a Friday evening. Ship it?"),
    Achievement("archaeologist", "Archaeologist", "a failure on a line nobody touched for 5+ years"),
    Achievement("glass_cannon", "Glass Cannon", "100% coverage, and still red"),
    Achievement("unstoppable", "Unstoppable", "a 100-test combo"),
]
YEAR = 365 * 86400


@dataclass
class RunFacts:
    ok: bool
    hour: int
    counts: Counter
    done: int
    weekday: int = 0  # Monday is 0
    warnings: int = 0
    prior_runs: list[dict] = field(default_factory=list)
    green_streak: int = 0  # including this run
    new_pb: bool = False
    longest_fixed_streak: int = 0  # the longest failing streak among tests fixed by this run
    coverage_files: list[tuple[int, float]] = field(default_factory=list)  # (statements, percent)
    coverage_total: float | None = None
    fail_under: float | None = None
    precision: int = 0
    oldest_blame: float | None = None  # age in seconds of the oldest line a failure was blamed on
    max_combo: int = 0


def earned(facts: RunFacts) -> list[Achievement]:
    prior = facts.prior_runs
    hits = {
        "first_blood": not facts.ok and bool(prior) and all(r.get("ok") for r in prior),
        "phoenix": facts.ok and len(prior) >= 5 and not any(r.get("ok") for r in prior[-5:]),
        "night_owl": 0 <= facts.hour < 5,
        "minimalist": any(0 < n <= 3 and pct >= 100 for n, pct in facts.coverage_files),
        "sniper": facts.fail_under is not None
        and facts.coverage_total is not None
        and round(facts.coverage_total, facts.precision) == facts.fail_under,
        "speedrunner": facts.new_pb,
        "surgeon": facts.ok and facts.longest_fixed_streak >= 5,
        "clean_sweep": facts.ok
        and facts.done >= 100
        and facts.counts.get("passed", 0) == facts.done
        and not facts.warnings,
        "centurion": facts.ok and facts.green_streak >= 100,
        "friday_deploy": facts.ok and facts.weekday == 4 and facts.hour >= 17,
        "archaeologist": facts.oldest_blame is not None and facts.oldest_blame >= 5 * YEAR,
        "glass_cannon": not facts.ok and facts.coverage_total is not None and facts.coverage_total >= 100,
        "unstoppable": facts.max_combo >= 100,
    }
    return [a for a in ALL if hits.get(a.key)]
