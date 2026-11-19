"""--glow-boss: the test suite is a boss. Every test that doesn't fail is a hit; every failure, one of yours."""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from rich.table import Table
from rich.text import Text

from . import render

HEARTS = 3
HIT_FLASH = 0.25  # seconds a hit keeps the boss pale and shaking

# name -> sprite; {e} marks the eyes, which change as the boss weakens
BOSSES: dict[str, list[str]] = {
    "Regression Lich": [" ▄▀▀▀▀▄ ", "▐ {e}  {e} ▌", " ▀▄▀▀▄▀ "],
    "Flaky Hydra": ["▄  ▄▀▄  ▄", "{e}▀▄{e}▄▀{e}", " ▀▄▄▄▄▄▀ "],
    "Merge Conflict Kraken": [" ▄▀▀▀▀▄ ", "▐ {e}  {e} ▌", "╱╲╱╲╱╲╱╲"],
    "Legacy Golem": ["▐█▀▀▀▀█▌", "▐▌{e}  {e}▐▌", "▐█▄▄▄▄█▌"],
    "Null Pointer Wyrm": ["   ▄▀▀▄▄ ", "▄▀  {e}  ▀▄", "▀▄▄▄▄▄▄▄▀"],
    "Off-by-One Ogre": ["▄█▀▀▀▀█▄", "█ {e}  {e} █", "▀█▄▀▀▄█▀"],
}
HP_BAR = ("#7f1d1d", "#ef4444", "#f97316")
BODY = ("#a855f7", "#ec4899")


@dataclass
class Fight:
    name: str
    sprite: list[str]
    hp: int  # one per test

    @classmethod
    def for_project(cls, project: str, hp: int = 0) -> Fight:
        """The same project always meets the same boss: its nemesis."""
        names = sorted(BOSSES)
        name = names[zlib.crc32(project.encode()) % len(names)]
        return cls(name, BOSSES[name], hp)

    def eyes(self, left: int) -> str:
        share = left / self.hp if self.hp else 0
        return "●" if share > 0.5 else "◦" if share > 0.2 else "✖"

    def sprite_text(self, left: int, heat: float, jolt: bool = False) -> Text:
        """``heat`` (0-1): how fresh the last hit is; under a barrage the boss stays pale but keeps its colour."""
        width = max(len(line.replace("{e}", "x")) for line in self.sprite)
        text = Text()
        for i, line in enumerate(self.sprite):
            line = line.replace("{e}", self.eyes(left)).ljust(width)
            line = (" " + line) if jolt and i % 2 == 0 else (line + " ")
            color = render.blend(render.gradient_at(BODY, i / max(len(self.sprite) - 1, 1)), "#ffffff", heat * 0.5)
            text.append(line, style=f"bold {color}" if heat > 0.5 else color)
            if i < len(self.sprite) - 1:
                text.append("\n")
        return text


def hearts(lost: int) -> Text:
    lost = min(lost, HEARTS)
    return Text.assemble(("❤" * (HEARTS - lost), "bold #ef4444"), ("♡" * lost, "#4b5563"))


def arena(fight: Fight, left: int, wounds: int, now: float, last_hit: float | None, combo: int) -> Table:
    """The live view: the boss with its HP bar, and you with your hearts."""
    heat = max(0.0, 1 - (now - last_hit) / HIT_FLASH) if last_hit is not None else 0.0
    jolt = heat > 0 and int(now * 12) % 2 == 0  # every other refresh
    grid = Table.grid(padding=(0, 2), expand=True)
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1)
    title = Text.assemble("👹 ", render.gradient_text(fight.name.upper(), BODY), (f"   HP {left}/{fight.hp}", "dim"))
    you = Text.assemble("🧙 you  ", hearts(wounds))
    if wounds >= HEARTS:
        you.append("  knocked out, still swinging", style="dim")
    elif combo >= 10:
        you.append(f"  ⚡ ×{combo} — every hit a crit", style="bold #facc15")
    grid.add_row(
        fight.sprite_text(left, heat, jolt),
        render_lines(title, render.GlowBar(left, fight.hp or 1, HP_BAR), you),
    )
    return grid


def render_lines(*rows) -> Table:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    for row in rows:
        table.add_row(row)
    return table


def outcome(fight: Fight, left: int, wounds: int, hits: int, duration: str, interrupted: bool) -> Text:
    name = f"the {fight.name}"
    if interrupted:
        return Text.assemble("🏃 ", ("you fled", "bold yellow"), (f" from {name}", "dim"))
    if left == 0 and not wounds:
        return Text.assemble(
            "🏆 ",
            render.gradient_text("VICTORY", render.GRADIENTS["fire"]),
            ("  ", ""),
            (f"{name} falls", "bold"),
            (f" · {hits} hits in {duration}", "dim"),
        )
    if wounds >= HEARTS:
        return Text.assemble(
            "💀 ", ("DEFEATED", "bold red"), (f" by {name}", "bold"), (f" · it survives with {left} HP", "dim")
        )
    return Text.assemble(
        "⚔ ",
        (f"{name} survives with {left} HP", "bold"),
        ("  · you have ", "dim"),
        hearts(wounds),
        (" left", "dim"),
    )
