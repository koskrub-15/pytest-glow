"""Tips: what the timings say to do about a slow suite, with the numbers behind them."""

from __future__ import annotations

from dataclasses import dataclass

from . import render

MAX_TIPS = 3
MIN_SECONDS = 0.5  # a tip has to be worth at least this much of the run…
MIN_SHARE = 0.1  # …and this share of it
MIN_CALLS = 5  # a function-scoped fixture set up fewer times than this isn't worth a scope

# libraries slow on purpose, and how to make them quick in tests
SLOW_ON_PURPOSE = {
    "argon2": "it's slow on purpose; in tests: PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)",
    "bcrypt": "it's slow on purpose; in tests: bcrypt.gensalt(rounds=4)",
    "passlib": "it's slow on purpose; in tests, the fewest rounds: CryptContext(..., bcrypt__rounds=4)",
    "botocore": "boto3 clients are slow to make: make them once, in a session-scoped fixture",
    "faker": "Faker() is slow to make: make one, in a session-scoped fixture",
}


@dataclass(frozen=True)
class Tip:
    saves: float  # seconds of the run it's about, to rank tips by
    what: str
    do: str


def _worth(seconds: float, duration: float) -> bool:
    return seconds >= MIN_SECONDS and duration > 0 and seconds / duration >= MIN_SHARE


def _share(seconds: float, duration: float) -> str:
    return f"{render.fmt_dur(seconds)}, {seconds / duration:.0%} of the run"


def fixture_scopes(fixtures: dict, mine: set, duration: float) -> list[Tip]:
    """Function-scoped fixtures of the project that are set up over and over, and take a good part of the run."""
    tips = []
    for (name, scope), spent in fixtures.items():
        if scope != "function" or name not in mine or spent.count < MIN_CALLS or not _worth(spent.total, duration):
            continue
        each = render.fmt_dur(spent.total / spent.count)
        tips.append(
            Tip(
                spent.total,
                f"{name} is set up {spent.count}× at {each} each: {_share(spent.total, duration)}",
                'if tests don\'t change what it gives them, @pytest.fixture(scope="module") sets it up once a file',
            )
        )
    return tips


def slow_libraries(spent_by_lib: dict, duration: float) -> list[Tip]:
    """Libraries known to be slow on purpose, or slow to set up, taking a good part of the run."""
    return [
        Tip(seconds, f"{name} takes {_share(seconds, duration)}", SLOW_ON_PURPOSE[name])
        for name, seconds in spent_by_lib.items()
        if name in SLOW_ON_PURPOSE and _worth(seconds, duration)
    ]


def sleeps(slept: dict, duration: float) -> list[Tip]:
    """Time spent in time.sleep, by test."""
    total = sum(slept.values())
    if not _worth(total, duration):
        return []
    worst = sorted(slept.items(), key=lambda item: -item[1])[:2]
    named = ", ".join(f"{render.test_name(nodeid)} {render.fmt_dur(sec)}" for nodeid, sec in worst)
    return [
        Tip(
            total,
            f"tests sleep for {_share(total, duration)} ({named})",
            "poll for what they wait for instead, or fake the clock (time-machine, freezegun)",
        )
    ]


def tips(*groups: list[Tip]) -> list[Tip]:
    return sorted((tip for group in groups for tip in group), key=lambda tip: -tip.saves)[:MAX_TIPS]
