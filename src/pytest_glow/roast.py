"""--glow-roast: one line of abuse under every failure, aimed at what actually went wrong."""

from __future__ import annotations

import random
import re
import time

from .blame import Blame, ago
from .history import is_flaky

ANYTHING = [
    "the test had one job",
    "assert is not a suggestion",
    "confidently wrong: the best kind of wrong",
    "have you tried turning it off and on again",
    "this is fine 🔥",
    "ship it anyway?",
    "red. just red.",
    "the CI is going to love this one",
]
BY_TYPE = {
    "AssertionError": ["expected: working code. got: this", "the code and the test disagree, and the test is winning"],
    "KeyError": ["{detail}: it was never there. it was never going to be there.", "dict.get() exists, just saying"],
    "AttributeError": ["it has no {attr}, and it never promised one", "duck typing, minus the duck"],
    "TypeError": ["python's way of saying 'what did you expect'", "type hints are free, you know"],
    "ValueError": ["right type, wrong vibes"],
    "IndexError": ["off by one: the oldest bug in the book, found again", "the list ends before your optimism does"],
    "ZeroDivisionError": ["dividing by zero in {year}. bold."],
    "ImportError": ["can't even import. we never got to the test part"],
    "ModuleNotFoundError": ["can't even import. we never got to the test part", "pip install confidence"],
    "ConnectionError": ["a unit test that needs a network: that's not a test, that's a prayer"],
    "ConnectionRefusedError": ["is the database in the room with us right now?"],
    "TimeoutError": ["waited. and waited. it's not coming back."],
    "RecursionError": ["to understand recursion, see: this failure"],
    "NotImplementedError": ["TODO: everything"],
    "FileNotFoundError": ["the file is in another castle"],
    "RuntimeError": ["it ran. that was the problem."],
}
_TYPE = re.compile(r"^([A-Za-z_][\w.]*?)(?::\s*(.*))?$")
_NUMBERS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*≠\s*(-?\d+(?:\.\d+)?)\s*$")
_NONE_ATTR = re.compile(r"'NoneType' object has no attribute")
_ATTR = re.compile(r"has no attribute '([^']+)'")


def _kind(message: str) -> tuple[str, str]:
    """ "KeyError: 'id'" -> ("KeyError", "'id'"); a message that names no exception -> ("", message)."""
    found = _TYPE.match(message.split("\n", 1)[0])
    if found is None or not found.group(1)[:1].isupper():
        return "", message
    return found.group(1).rsplit(".", 1)[-1], found.group(2) or ""


def roast(
    message: str,
    *,
    summary: str = "",
    blame: Blame | None = None,
    outcomes: str = "",
    rnd: random.Random | None = None,
    now: float | None = None,
) -> str:
    """``message``: the crash message; ``summary``: glow's own (``4.0 ≠ 4.5``); ``outcomes``: the test's history."""
    rnd = rnd or random.Random()
    now = time.time() if now is None else now
    kind, detail = _kind(message)
    lines: list[str] = []
    numbers = _NUMBERS.match(summary)
    if numbers:
        left, right = float(numbers.group(1)), float(numbers.group(2))
        off = abs(left - right)
        lines.append(f"off by {off:g}. so close, and yet so red.")
    if _NONE_ATTR.search(message):
        lines.append("None strikes again: the billion-dollar mistake, now with your name on it")
    attr = _ATTR.search(message)
    for line in BY_TYPE.get(kind, []):
        if "{attr}" in line and attr is None:
            continue
        lines.append(
            line.format(detail=detail or kind, attr=attr.group(1) if attr else "", year=time.gmtime(now).tm_year)
        )
    if blame is not None:
        if blame.when is None:
            lines.append("not even committed and already broken. efficient.")
        elif blame.yours and now - blame.when < 3600:
            lines.append(f"you wrote this {ago(now - blame.when)}. it didn't last an hour.")
        elif blame.yours:
            lines.append(f"you wrote this {ago(now - blame.when)}, and it's been waiting for you ever since")
        else:
            lines.append(f"git blame says {blame.author}. awkward.")
    streak = len(outcomes) - len(outcomes.rstrip("FE"))
    if streak >= 2:
        lines.append(f"red {streak + 1} runs in a row. at this point it's a feature.")
    elif is_flaky(outcomes):
        failed = sum(c in "FE" for c in outcomes)
        lines.append(f"failed {failed} of its last {len(outcomes)}: not a test, a coin flip")
    return rnd.choice(lines or ANYTHING)
