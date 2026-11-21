"""Daily quests: three small goals a day, the same all day, paid in XP. Utterly optional, like the rest."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

from rich.text import Text

from . import render

PER_DAY = 3
SWEEP_XP = 100  # for finishing all of a day's quests


@dataclass(frozen=True)
class Quest:
    key: str
    title: str  # {goal} is filled in
    xp: int
    best: bool = False  # progress is the best single run, not a running total


ALL = {
    q.key: q
    for q in (
        Quest("fixer", "fix {goal} tests", 60),
        Quest("greens", "{goal} green runs", 40),
        Quest("early", "green before 10am", 50),
        Quest("combo", "a ×{goal} combo", 40, best=True),
        Quest("volume", "run {goal} tests", 30),
        Quest("spotless", "a green run, no warnings, no skips", 40),
        Quest("speed", "beat your personal best", 80),
        Quest("comeback", "red → green", 50),
    )
}


@dataclass
class RunFacts:
    ok: bool
    ran: int
    fixed: int
    max_combo: int
    hour: int
    new_pb: bool
    comeback: bool
    spotless: bool


def enabled() -> bool:
    return os.environ.get("PYTEST_GLOW_QUESTS", "").strip().lower() not in ("0", "false", "no", "off")


def _nice(n: float) -> int:
    """Rounded to a number a person would pick: 10, 25, 50, 100, 250, 500…"""
    for step in (1000, 100, 50, 10, 5):
        if n >= step * 2:
            return int(round(n / step) * step)
    return max(int(n), 1)


def pick(day: str, project: str, *, typical: int, hour: int, has_best: bool) -> list[list]:
    """Today's quests, as [key, goal]: the same for the whole day in a project."""
    rng = random.Random(f"{day}:{project}")
    pool = [key for key in ALL if not (key == "early" and hour >= 10) and not (key == "speed" and not has_best)]
    if typical < 20:
        pool.remove("combo")  # not enough tests in a run to get there
    goals = {
        "fixer": 3,
        "greens": 3,
        "combo": _nice(min(max(typical * 0.6, 10), 100)),
        "volume": _nice(max(typical * 5, 100)),
    }
    return [[key, goals.get(key, 1)] for key in rng.sample(pool, PER_DAY)]


def today(state: dict, project: str, *, typical: int, hour: int, has_best: bool) -> dict:
    """``state`` as it is today: kept if it's from today, new quests if not."""
    day = time.strftime("%Y-%m-%d")
    if state.get("day") == day and state.get("q"):
        return state
    return {"day": day, "q": pick(day, project, typical=typical, hour=hour, has_best=has_best), "p": {}, "done": []}


def _progress(key: str, facts: RunFacts) -> int:
    return {
        "fixer": facts.fixed,
        "greens": int(facts.ok),
        "early": int(facts.ok and facts.hour < 10),
        "combo": facts.max_combo,
        "volume": facts.ran,
        "spotless": int(facts.ok and facts.spotless),
        "speed": int(facts.new_pb),
        "comeback": int(facts.comeback),
    }[key]


def advance(state: dict, facts: RunFacts) -> list[tuple[Quest, int]]:
    """Counts the run towards today's quests; the ones it finished, with their goals."""
    finished = []
    progress, done = state.setdefault("p", {}), state.setdefault("done", [])
    for key, goal in state.get("q", []):
        quest = ALL.get(key)
        if quest is None or key in done:
            continue
        got = _progress(key, facts)
        progress[key] = max(progress.get(key, 0), got) if quest.best else progress.get(key, 0) + got
        if progress[key] >= goal:
            done.append(key)
            finished.append((quest, goal))
    return finished


def swept(state: dict) -> bool:
    return bool(state.get("q")) and len(state.get("done", [])) == len(state["q"])


def xp(finished: list[tuple[Quest, int]], state: dict) -> int:
    return sum(quest.xp for quest, _ in finished) + (SWEEP_XP if finished and swept(state) else 0)


def lines(state: dict, finished: list[tuple[Quest, int]]) -> list[Text]:
    """What the verdict says about today's quests."""
    out = []
    for quest, goal in finished:
        line = Text("📜 ")
        line.append_text(render.gradient_text("quest complete", render.GRADIENTS["gold"]))
        line.append(f"  {quest.title.format(goal=goal)}", style="bold")
        line.append(f"  +{quest.xp} XP", style="bold magenta")
        out.append(line)
    if finished and swept(state):
        line = Text("📜 ")
        line.append_text(render.gradient_text("all dailies done", render.GRADIENTS["gold"]))
        line.append(f"  +{SWEEP_XP} XP", style="bold magenta")
        line.append(" · new ones tomorrow", style="dim")
        out.append(line)
    elif not swept(state):
        line = Text("📜 ", style="dim")
        line.append("dailies ", style="dim")
        for i, (key, goal) in enumerate(state.get("q", [])):
            quest = ALL.get(key)
            if quest is None:
                continue
            if i:
                line.append(" · ", style="dim")
            title = quest.title.format(goal=goal)
            if key in state.get("done", []):
                line.append(f"✓ {title}", style="green")
                continue
            line.append(title)
            if goal > 1:
                line.append(f" {min(state.get('p', {}).get(key, 0), goal)}/{goal}", style="dim")
        out.append(line)
    return out
