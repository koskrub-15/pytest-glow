from collections import Counter

import pytest

from pytest_glow import coverage, render
from pytest_glow.history import History, is_flaky


@pytest.mark.parametrize(
    ("lines", "expected"),
    [([], ""), ([7], "7"), ([1, 2, 3], "1-3"), ([1, 2, 5, 7, 8, 9], "1-2, 5, 7-9")],
)
def test_ranges(lines, expected):
    assert coverage.ranges(lines) == expected


@pytest.mark.parametrize(
    ("percent", "precision", "expected"),
    [(66.666, 0, "67%"), (99.6, 0, "99%"), (100.0, 0, "100%"), (0.2, 0, "1%"), (0.0, 0, "0%"), (98.857, 2, "98.86%")],
)
def test_fmt_percent_never_lies_about_100_or_0(percent, precision, expected):
    assert coverage.fmt_percent(percent, precision) == expected


@pytest.mark.parametrize(
    ("outcomes", "flaky"),
    [("", False), ("PPPP", False), ("PPF", False), ("FFPP", False), ("PFP", True), ("PSFSP", True), ("FPFP", True)],
)
def test_is_flaky(outcomes, flaky):
    assert is_flaky(outcomes) is flaky


def test_strip_buckets_keep_the_worst_outcome():
    strip = render.strip(["passed"] * 9 + ["failed"], total=10, width=5)
    assert strip.plain == "━" * 5
    assert [span.style for span in strip.spans][-1] == render.HEX["failed"]


def test_strip_pads_unfinished_tests():
    strip = render.strip(["passed"], total=4, width=10)
    assert len(strip.plain) == 10
    assert [span.style for span in strip.spans] == [render.HEX["passed"]] + [render._TRACK] * 3


def test_proportion_bar_fills_the_width_and_keeps_rare_outcomes_visible():
    bar = render.proportion_bar(Counter(passed=998, failed=1, skipped=1), width=50)
    assert len(bar.plain) == 50
    assert {span.style for span in bar.spans} == {render.HEX[c] for c in ("passed", "failed", "skipped")}


def test_strip_flashes_fresh_tests():
    strip = render.strip(["passed", "passed"], total=2, width=2, ages=[10.0, 0.0])
    assert [span.style for span in strip.spans] == [render.HEX["passed"], "bold #ffffff"]


def test_glow_bar_fills_proportionally():
    bar = render.glow_bar(1, 2, 10, render.GRADIENTS["green"])
    assert len(bar.plain) == 10
    assert bar.spans[-1].style == render._TRACK
    assert sum(1 for span in bar.spans if span.style != render._TRACK) == 5


def test_counts_are_not_dimmed_by_the_separator():
    text = render.counts_text(Counter(passed=2, failed=1), compact=False)
    assert text.style == ""


@pytest.mark.parametrize(
    ("seconds", "expected"), [(0.0001, "<1ms"), (0.25, "250ms"), (3.14159, "3.14s"), (125, "2m05s")]
)
def test_fmt_dur(seconds, expected):
    assert render.fmt_dur(seconds) == expected


def test_crash_message_strips_pytest_colours():
    class Crash:
        message = "\x1b[31massert\x1b[0m 1 == 2\nmore"

    class Report:
        longrepr = type("Repr", (), {"reprcrash": Crash()})()

    assert render.crash_message(Report()) == "assert 1 == 2"


class FakeCache(dict):
    def get(self, key, default):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value


def test_history_round_trip():
    cache = FakeCache()
    history = History(cache)
    history.record(
        {"t::a": ("passed", 0.5), "t::b": ("failed", 1.0)}, 2.0, ok=False, failed=1, coverage=(80.0, {"m.py": 80.0})
    )
    history.save()

    again = History(cache)
    assert again.last_outcome("t::a") == "P"
    assert again.last_outcome("t::b") == "F"
    assert again.last_coverage() == 80.0
    assert again.coverage == {"m.py": 80.0}
    assert again.green_streak() == 0
    assert again.last_comparable_run(2)["d"] == 2.0


def test_history_survives_a_corrupt_cache():
    cache = FakeCache({"glow/history": "garbage"})
    assert History(cache).runs == []
    assert not History(None).enabled
