"""--glow-chat: a stream chat beside the live view, reacting to the run as it happens.

The viewers are made up; what they react to isn't: the tests, the failures, the combo, the slow ones.
"""

from __future__ import annotations

import random
import zlib
from collections import deque
from dataclasses import dataclass

from rich.panel import Panel
from rich.text import Text

from . import render

WIDTH = 40  # columns the chat takes beside the live view
SIDE_FROM = 120  # a terminal this wide gets the chat beside the live view; a narrower one, under it
LINES = 8  # messages kept on screen
GAP = 0.3  # seconds between idle chatter at least: something that happens always gets said
RESTLESS = 2.5  # seconds of nothing before chat gets restless
SLOW = 3.0  # seconds a test runs before chat notices
MILESTONES = (10, 25, 50, 100, 250, 500, 1000)

# fmt: off
_FIRST = [
    "segfault", "null", "async", "flaky", "mock", "pip", "venv", "lint", "merge", "rebase", "sudo", "heisen", "race",
    "cache", "yaml", "regex", "legacy", "tabs", "spaces", "monkeypatch", "fixture", "mutex", "daemon", "kernel",
    "docker", "git", "unicode", "lambda", "tuple", "walrus", "semicolon",
]
_LAST = [
    "_enjoyer", "_goblin", "42", "_andy", "_main", "_irl", "420", "_btw", "_dev", "_fan", "_lord", "69", "_gremlin",
    "_hater", "_stan", "2003", "_xd", "_bot",
]
# fmt: on
COLORS = ("#f472b6", "#22d3ee", "#a78bfa", "#facc15", "#4ade80", "#fb923c", "#60a5fa", "#f87171", "#e879f9")

START = [
    "first",
    "LETS GOOO",
    "{project} any% speedrun, {total} tests",
    "chat is this real",
    "o7",
    "just got here what did i miss",
    "{total} tests? we're gonna be here a while",
]
PASS = ["W", "clean", "ez", "+1", "nice", "sheesh", "{test} carried", "green is my favourite colour", "ok ok ok"]
COMBO = ["×{n} COMBO 🔥", "no way ×{n}", "clip it ×{n}", "cooking 🔥🔥🔥", "chat is this a speedrun", "×{n} Pog"]
FAIL = [
    "L",
    "F",
    "F in chat",
    "skill issue",
    "KEKW",
    "{test} 💀",
    "{message}?? 💀",
    "who wrote {test}",
    "ratio",
    "unsubbed",
]
BROKE = ["NOOOO the ×{n}", "×{n} combo thrown 😭", "C-C-C-COMBO BREAKER", "{n} in a row and then THAT"]
NETWORK = ["is the database in the room with us", "postgres said no", "works on my machine"]
SKIP = ["skipped? coward", "skip 👀", "we don't talk about that one"]
SLOW_TEST = [
    "ResidentSleeper",
    "{test} takes {secs} 💀",
    "is this a loading screen",
    "buffering…",
    "touch grass while it runs",
]
RESTLESS_LINES = ["is it stuck?", "zzz", "any% no-skip?", "chat is it frozen", "🦗", "lag?"]
GREEN = ["GG", "GG EZ", "clip that", "W streamer", "subbed", "all green PogChamp"]
RED = ["GG go next", "F", "chat we lost", "uninstall", "it's never the code. it's always the code", "L + ratio"]


def username(rnd: random.Random) -> str:
    name = rnd.choice(_FIRST) + rnd.choice(_LAST)
    return f"xX_{name}_Xx" if rnd.random() < 0.08 else name


def viewers_text(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


@dataclass
class Message:
    user: str
    text: str
    at: float

    @property
    def color(self) -> str:
        return COLORS[zlib.crc32(self.user.encode()) % len(COLORS)]

    def line(self) -> Text:
        return Text.assemble((self.user, f"bold {self.color}"), (": ", "dim"), self.text)


class Chat:
    def __init__(self, project: str, rnd: random.Random | None = None) -> None:
        self.rnd = rnd or random.Random()
        self.project = project
        self.messages: deque[Message] = deque(maxlen=LINES)
        self.users = [username(self.rnd) for _ in range(24)]
        self.viewers = self.rnd.randint(3, 40)
        self.peak = self.viewers
        self.last = 0.0
        self._noticed: set[str] = set()

    def say(self, now: float, lines: list[str], **facts: object) -> Message:
        message = Message(self.rnd.choice(self.users), self.rnd.choice(lines).format(**facts), now)
        self.messages.append(message)
        self.last = now
        return message

    def _maybe(self, now: float, odds: float, lines: list[str], **facts: object) -> None:
        if now - self.last >= GAP and self.rnd.random() < odds:
            self.say(now, lines, **facts)

    def _audience(self, factor: float) -> None:
        self.viewers = max(1, round(self.viewers * factor))
        self.peak = max(self.peak, self.viewers)

    def started(self, now: float, total: int) -> None:
        self.say(now, START, project=self.project, total=total)

    def passed(self, now: float, nodeid: str, combo: int) -> None:
        self._audience(self.rnd.uniform(1.0, 1.06) + 0.4 / self.viewers)
        if combo in MILESTONES:
            self._audience(1.25)
            self.say(now, COMBO, n=combo)
        else:
            self._maybe(now, 0.15, PASS, test=render.test_name(nodeid))

    def failed(self, now: float, nodeid: str, message: str, broke: int | None) -> None:
        self._audience(self.rnd.uniform(0.82, 0.95))
        test = render.test_name(nodeid)
        if broke:
            self.say(now, BROKE, n=broke)
        if "Connection" in message or "connect" in message:
            self.say(now, NETWORK)
        said = message.split(": ", 1)[-1].strip()  # what went wrong, not what it's called
        self.say(now, FAIL, test=test, message=said[:24] or "what")

    def skipped(self, now: float, nodeid: str) -> None:
        self._maybe(now, 0.35, SKIP, test=render.test_name(nodeid))

    def tick(self, now: float, running: dict[str, float]) -> None:
        """Every frame: ``running`` is nodeid -> when it started."""
        for nodeid, started in running.items():
            if now - started >= SLOW and nodeid not in self._noticed:
                self._noticed.add(nodeid)
                self.say(now, SLOW_TEST, test=render.test_name(nodeid), secs=render.fmt_dur(now - started))
        if self.messages and now - self.last >= RESTLESS:
            self.say(now, RESTLESS_LINES)

    def finished(self, now: float, ok: bool) -> Message:
        self._audience(1.3 if ok else 0.7)
        return self.say(now, GREEN if ok else RED)

    def panel(self, height: int) -> Panel:
        lines = [message.line() for message in list(self.messages)[-height:]]
        for line in lines:
            line.truncate(WIDTH - 4, overflow="ellipsis")
        body = Text("\n").join([Text()] * (height - len(lines)) + lines)  # new messages come in at the bottom
        title = Text.assemble(("● LIVE", "bold #ef4444"), (f" · {viewers_text(self.viewers)} watching", "dim"))
        return Panel(body, title=title, title_align="left", border_style="#7c3aed", width=WIDTH, padding=(0, 1))
