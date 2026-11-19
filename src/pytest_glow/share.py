"""--glow-share: the run as a card, an SVG ready to post."""

from __future__ import annotations

import io
import time
from collections import Counter
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.text import Text

from . import render

WIDTH = 64


@dataclass
class Card:
    project: str
    icon: str
    word: str
    stops: tuple[str, ...]
    counts: Counter
    details: list[Text] = field(default_factory=list)  # time, records, combos, coverage: the verdict's lines


def render_card(card: Card) -> render.GlowPanel:
    inner = WIDTH - 4
    head = Text.assemble(render.gradient_text(" ✦ glow ", render.GRADIENTS["glow"], background=True), "  ")
    head.append(card.project, style="bold")
    date = time.strftime("%d %b %Y")
    head.append(" " * max(inner - len(head) - len(date), 1) + date, style="dim")
    verdict = Text.assemble(render.gradient_text(f" {card.icon} {card.word.upper()} ", card.stops, background=True))
    lines = [
        head,
        Text(""),
        verdict,
        Text(""),
        render.counts_text(card.counts, compact=False),
        render.proportion_bar(card.counts, inner) if card.counts else Text("━" * inner, style="grey30"),
        *card.details,
    ]
    return render.GlowPanel(Group(*lines), card.stops)


def save(card: Card, path: str) -> None:
    console = Console(
        record=True, width=WIDTH, file=io.StringIO(), force_terminal=True, color_system="truecolor", highlight=False
    )
    console.print(render_card(card))
    console.save_svg(path, title=f"pytest · {card.project}")
