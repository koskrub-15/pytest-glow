"""XP and levels: every run earns some, kept per project in the history."""

from __future__ import annotations

from rich.text import Text

from . import render

# the title you hold from each level on
TITLES = (
    (1, "Print Debugger"),
    (3, "Assert Apprentice"),
    (5, "Fixture Fiddler"),
    (8, "Mock Wrangler"),
    (12, "Flake Hunter"),
    (16, "Assert Whisperer"),
    (20, "Coverage Monk"),
    (25, "Regression Slayer"),
    (30, "Test Necromancer"),
    (40, "Lord of the Green"),
    (50, "The One Who Runs pytest"),
)
MAX_PASS_XP = 200  # a 20 000-test suite shouldn't level up twenty times a run
PRESTIGE_AT = 50  # past this level: back to Lv 1, with a star to show for it


def xp_for(*, passed: int, ok: bool, max_combo: int, fixed: int, boss_won: bool, shiny: bool) -> int:
    xp = min(passed, MAX_PASS_XP)
    xp += 25 if ok else 0
    xp += max_combo // 10 * 2
    xp += 10 * fixed
    xp += 100 if boss_won else 0
    xp += 250 if shiny else 0
    return xp


def to_next(level: int) -> int:
    """XP from ``level`` to the next one."""
    return 100 + 50 * (level - 1)


def _cycle() -> int:
    """XP from Lv 1 through PRESTIGE_AT."""
    return sum(to_next(level) for level in range(1, PRESTIGE_AT + 1))


def stars(xp: int) -> int:
    """Times through every level and back to Lv 1."""
    return xp // _cycle()


def level_of(xp: int) -> tuple[int, int, int]:
    """(level, XP into it, XP it takes), since the last prestige."""
    xp %= _cycle()
    level = 1
    while xp >= to_next(level):
        xp -= to_next(level)
        level += 1
    return level, xp, to_next(level)


def rank(xp: int) -> tuple[int, int]:
    """(stars, level): what a level up compares."""
    return stars(xp), level_of(xp)[0]


def stars_text(xp: int) -> Text:
    n = stars(xp)
    return Text("★" * n if n <= 3 else f"★×{n}", style="bold #facc15") if n else Text()


def title(level: int) -> str:
    return next(name for since, name in reversed(TITLES) if level >= since)


def xp_bar(into: int, needed: int, width: int = 10) -> Text:
    filled = round(width * into / needed) if needed else width
    bar = Text()
    for i in range(width):
        if i < filled:
            bar.append("▰", style=render.gradient_at(render.GRADIENTS["glow"], i / max(width - 1, 1)))
        else:
            bar.append("▱", style=render._TRACK)
    return bar


def xp_line(before: int, gained: int) -> Text:
    """'+212 XP  Lv 7 Fixture Fiddler ▰▰▰▱▱ 340/450', or a LEVEL UP, or a PRESTIGE."""
    old = level_of(before)[0]
    level, into, needed = level_of(before + gained)
    if stars(before + gained) > stars(before):
        line = Text.assemble("★ ", render.gradient_text("PRESTIGE", render.GRADIENTS["fire"]), "  ")
        line.append(f"past Lv {PRESTIGE_AT}: back to Lv {level}, with a star ", style="bold")
        line.append_text(stars_text(before + gained))
        line.append(f"  +{gained} XP", style="dim")
        return line
    if level > old:
        line = Text.assemble("⬆ ", render.gradient_text("LEVEL UP", render.GRADIENTS["fire"]), "  ")
        line.append(f"Lv {level} · {title(level)}", style="bold")
        if title(level) != title(old):
            line.append("  new title!", style="bold #facc15")
        line.append(f"  +{gained} XP", style="dim")
        return line
    line = Text.assemble(("✦ ", "magenta"), (f"+{gained} XP", "bold magenta"), "  ")
    if stars(before + gained):
        line.append_text(stars_text(before + gained))
        line.append(" ")
    line.append(f"Lv {level} {title(level)} ", style="dim")
    line.append_text(xp_bar(into, needed))
    line.append(f" {into}/{needed}", style="dim")
    return line
