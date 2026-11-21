"""pytest --glow-wrapped: everything this project's history remembers, as a year-in-review."""

from __future__ import annotations

import io
import itertools
import statistics
import time

from rich.console import Console, Group
from rich.text import Text

from . import achievements as ach
from . import progress, render
from .boss import LOOT
from .history import FAILING, History


def _flips(outcomes: str) -> int:
    seq = [c in FAILING for c in outcomes if c in FAILING or c == "P"]
    return sum(1 for a, b in itertools.pairwise(seq) if a != b)


def _duration(seconds: float) -> str:
    if seconds < 60:
        return render.fmt_dur(seconds)
    minutes = round(seconds / 60)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _hours(hours: list[int]) -> Text:
    top = max(hours) or 1
    text = Text()
    for i, n in enumerate(hours):
        level = n / top
        style = render.gradient_at(render.GRADIENTS["glow"], i / 23) if n else render._TRACK
        text.append(render.SPARKS[round(level * (len(render.SPARKS) - 1))], style=style)
    return text


def quip(green_rate: float, night_share: float) -> str:
    if night_share >= 0.3:
        return "Go to sleep. The tests will still be red tomorrow."
    if green_rate >= 0.95:
        return "Your CI fears you."
    if green_rate >= 0.8:
        return "Mostly green. Mostly."
    if green_rate >= 0.5:
        return "Red, green, red, green: a Christmas tree of a codebase."
    return "Your tests are more of a suggestion."


def _row(icon: str, label: str, value: Text | str) -> Text:
    line = Text.assemble(f"  {icon} ", (f"{label:<24}", "dim"))
    line.append_text(value if isinstance(value, Text) else Text(value, style="bold"))
    return line


def render_wrapped(history: History, project: str) -> render.GlowPanel | Text:
    life, runs, tests = history.life, history.runs, history.tests
    if not life and not runs:
        return Text("  no history here yet: run your tests with glow first, then come back", style="dim")

    n_runs = life.get("runs") or len(runs)
    greens = life.get("greens", sum(1 for r in runs if r.get("ok")))
    n_tests = life.get("tests") or sum(r.get("n", 0) for r in runs)
    spent = life.get("time") or sum(r.get("d", 0) for r in runs)
    since = life.get("since") or (runs[0]["t"] if runs else time.time())
    hours = life.get("hours") or [0] * 24
    green_rate = greens / n_runs if n_runs else 0
    night_share = sum(hours[:5]) / max(sum(hours), 1)

    title = Text.assemble(
        "  ",
        render.gradient_text("✦ YOUR PYTEST WRAPPED ✦", render.GRADIENTS["glow"]),
        ("   ", ""),
        (project, "bold"),
        (f" · since {time.strftime('%d %b %Y', time.localtime(since))}", "dim"),
    )
    big = Text("  ")
    for value, label in (
        (f"{n_runs:,}".replace(",", " "), "runs"),
        (f"{n_tests:,}".replace(",", " "), "tests"),
        (_duration(spent), "of testing"),
        (f"{green_rate:.0%}", "green"),
    ):
        big.append(value, style="bold")
        big.append(f" {label}    ", style="dim")
    lines: list = [title, Text(""), big]

    xp = history.xp
    if xp:
        level, into, needed = progress.level_of(xp)
        lv = Text.assemble("  ", (f"Lv {level} {progress.title(level)}  ", "bold magenta"))
        lv.append_text(progress.xp_bar(into, needed, 14))
        lv.append(f"  {xp:,} XP".replace(",", " "), style="dim")
        lines += [Text(""), lv]

    records = []
    streak = max(life.get("best_streak", 0), history.greens)
    if streak:
        records.append(_row("🔥", "longest green streak", f"{streak} runs"))
    if life.get("best_combo"):
        records.append(_row("⚡", "best combo", f"×{life['best_combo']}"))
    if history.best:
        n, best = max(history.best.items(), key=lambda item: int(item[0]))
        records.append(_row("🏆", "fastest green run", f"{render.fmt_dur(best)} for {n} tests"))
    if life.get("fixed"):
        records.append(_row("🩹", "tests fixed", str(life["fixed"])))

    if records:
        lines += [Text(""), Text("  records", style="bold dim"), *records]

    shame = []
    failing = [(sum(c in FAILING for c in t.get("o", "")), nodeid) for nodeid, t in tests.items()]
    worst = max(failing, default=(0, ""))
    if worst[0] >= 2:
        shame.append(_row("💀", "failed the most lately", Text.assemble(render.nodeid_text(worst[1]))))
    flaky = max(((_flips(t.get("o", "")), nodeid) for nodeid, t in tests.items()), default=(0, ""))
    if flaky[0] >= 2:
        trail = render.outcome_trail(tests[flaky[1]].get("o", ""))
        shame.append(_row("〰", "flakiest", Text.assemble(render.nodeid_text(flaky[1]), "  ", trail)))
    slow = max(
        ((statistics.median(t["d"]), nodeid) for nodeid, t in tests.items() if len(t.get("d", [])) >= 3),
        default=(0.0, ""),
    )
    if slow[0] >= 0.1:
        shame.append(
            _row("🐢", "slowest", Text.assemble(render.nodeid_text(slow[1]), (f"  {render.fmt_dur(slow[0])}", "dim")))
        )
    if shame:
        lines += [Text(""), Text("  hall of shame", style="bold dim"), *shame]

    if sum(hours):
        peak = max(range(24), key=lambda h: hours[h])
        when = Text.assemble("  ", _hours(hours), (f"   mostly around {peak:02d}:00", "dim"))
        if night_share:
            when.append(f" · {night_share:.0%} after midnight", style="dim")
        lines += [
            Text(""),
            Text("  when you test", style="bold dim"),
            when,
            Text("  0h" + " " * 19 + "23h", style="dim"),
        ]

    extras = Text("  ")
    won, lost = life.get("boss_won", 0), life.get("boss_lost", 0)
    if won or lost:
        extras.append("👹 ", style="")
        extras.append(f"{won} won · {lost} lost", style="bold")
        loot = life.get("loot", [])
        if loot:
            extras.append(f"   🎁 {len(loot)}/{len(LOOT)} ", style="bold")
            extras.append(" ".join(item.split(" ", 1)[0] for item in loot))
        extras.append("    ")
    extras.append(f"🏅 {len(history.achievements)}/{len(ach.ALL)} achievements", style="bold")
    if life.get("shiny"):
        extras.append(f"    ✦ {life['shiny']} shiny", style="bold #facc15")
    if life.get("quests"):
        extras.append(f"    📜 {life['quests']} quests", style="bold")
    lines += [Text(""), extras, Text(""), Text(f"  “{quip(green_rate, night_share)}”", style="italic")]
    return render.GlowPanel(Group(*lines), render.GRADIENTS["glow"], Text(" pytest-glow wrapped ", style="dim"))


def save(recap: render.GlowPanel | Text, path: str) -> None:
    console = Console(
        record=True, width=88, file=io.StringIO(), force_terminal=True, color_system="truecolor", highlight=False
    )
    console.print(recap)
    console.save_svg(path, title="pytest --glow-wrapped")
