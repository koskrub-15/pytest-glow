"""The glow pet: adopted once per project with ``pytest --glow-adopt``, and from then on, for good.

Green runs feed it and it grows up; a week of nothing but red and it dies. There's no way to give it back:
it lives outside the project's cache, so wiping that doesn't get rid of it either.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import sys
import time
import zlib
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import render

DIES_AFTER = 7 * 86400  # seconds of nothing but red runs
HEARTS = 5
STAGES = ((0, "egg"), (1, "hatchling"), (5, "kid"), (15, "teen"), (40, "adult"), (100, "elder"))
SPECIES = (  # (kind, happy, sick)
    ("rubber duck", "__(•<", "__(×<"),
    ("bug", "ϵ('Θ')϶", "ϵ(;Θ;)϶"),
    ("crab", "(\\/)(°,,°)(\\/)", "(\\/)(;,,;)(\\/)"),
    ("cat", "(=^･ω･^=)", "(=;ω;=)"),
    ("blob", "(ᵔᴥᵔ)", "(ᵔ︵ᵔ)"),
)
# The big ones, for the box under the verdict: {e} is an eye, {m} the mouth. Each as wide as its widest line.
ART = (
    (
        r"     __      ",
        r"   <({e} )___  ",
        r"    ( {m}  /  ",
        r"     `----'  ",
        r"   ~~~~~~~~~ ",
    ),
    (
        r"   \     /   ",
        r"   .-({e}{e})-.  ",
        r"  -|::::::|- ",
        r"  -|::::::|- ",
        r"   `-.{m}.-'   ",
    ),
    (
        r" (\/)   (\/) ",
        r"  \ \___/ /  ",
        r"   ( {e} {e} )   ",
        r"  /(__{m}__)\  ",
        r"   / / \ \   ",
    ),
    (
        r"   /\_/\     ",
        r"  ( {e}.{e} )    ",
        r"   > {m} <     ",
        r"  /|   |\  ~ ",
        r" (_|   |_)/  ",
    ),
    (
        r"   .-''-.    ",
        r"  / {e}  {e} \   ",
        r" |   {m}    |  ",
        r"  \      /   ",
        r"   `-..-'    ",
    ),
)
EYES = {"happy": "•", "sick": "×"}
MOUTHS = {"happy": ("._>", "w", "v", "w", "ᴗ"), "sick": ("._~", "~", "~", "~", "︵")}
EGG = (
    r"    .--.     ",
    r"   /    \    ",
    r"  |  ??  |   ",
    r"   \    /    ",
    r"    `--'     ",
)
GRAVE = (
    r"    _____    ",
    r"   /     \   ",
    r"  |  RIP  |  ",
    r"  |       |  ",
    r" ~|_______|~ ",
)
HATS = {"hatchling": r"   _/\/\_    ", "teen": r"     _=_     ", "adult": r"      ★      ", "elder": r"     ♛       "}
COLORS = ("#fde68a", "#a3e635", "#fb923c", "#f9a8d4", "#67e8f9")
MOODS = {
    "happy": (
        "your tests taste great today",
        "it hums the sound of a green bar",
        "it thinks you write good asserts",
        "it's napping on your coverage report",
        "it would like another green run, please",
        "it doesn't know what a flaky test is. keep it that way",
    ),
    "sick": (
        "it's coughing up stack traces",
        "it needs a green run. now.",
        "it looked at your diff and lay down",
        "the vet says: fix the tests",
        "it's too weak to hold an assert",
    ),
    "egg": ("something moves inside", "it's warm. it's listening to your tests", "it hatches on green"),
}

CONTRACT = (
    "it lives in this project for good: there's no --glow-abandon, and wiping the cache won't do it",
    "every green run feeds it and it grows up; a week of nothing but red and it dies",
    "it shows up after every run in your terminal (never in CI), so you'll always know how it's doing",
)


def _home() -> str:
    base = os.environ.get("PYTEST_GLOW_DATA")
    if base:
        return base
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "pytest-glow")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "pytest-glow")


def path_for(root: str) -> str:
    key = hashlib.sha1(os.path.realpath(root).encode()).hexdigest()[:16]
    return os.path.join(_home(), "pets", f"{key}.json")


def load(root: str) -> dict[str, Any] | None:
    try:
        with open(path_for(root), encoding="utf-8") as f:
            pet = json.load(f)
    except (OSError, ValueError):
        return None
    return pet if isinstance(pet, dict) and pet.get("name") else None


def save(root: str, pet: dict[str, Any]) -> None:
    path = path_for(root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(pet, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def adopt(root: str, name: str, now: float | None = None) -> dict[str, Any]:
    """A new egg; the pet before it, if it died, goes to the graveyard."""
    old = load(root)
    if old is not None and not old.get("died"):
        raise ValueError(f"{old['name']} already lives here")
    graves = [*old.get("graves", []), {k: old[k] for k in ("name", "species", "born", "died", "meals")}] if old else []
    project = os.path.basename(os.path.realpath(root))
    pet = {
        "name": name,
        "species": zlib.crc32(f"{project}/{name}".encode()) % len(SPECIES),
        "born": round(now if now is not None else time.time()),
        "meals": 0,
        "red_since": None,
        "died": None,
        "graves": graves,
    }
    save(root, pet)
    return pet


def stage(meals: int) -> str:
    return next(name for at, name in reversed(STAGES) if meals >= at)


def live(pet: dict[str, Any], ok: bool, now: float) -> list[str]:
    """A run happened: feed it, or let it get sicker. What changed: hatched, grew, recovered, sick, died."""
    if pet.get("died"):
        return []
    red_since = pet.get("red_since")
    if red_since is not None and now - red_since >= DIES_AFTER:
        pet["died"] = round(red_since + DIES_AFTER)
        return ["died"]
    if not ok:
        pet["streak"] = 0
        if red_since is None:
            pet["red_since"] = round(now)
            if not pet["meals"]:
                return []  # an egg doesn't get sick
            pet["sick_times"] = pet.get("sick_times", 0) + 1
            return ["sick"]
        return []
    before = stage(pet["meals"])
    pet["meals"] += 1
    pet["red_since"] = None
    pet["streak"] = pet.get("streak", 0) + 1
    pet["best_streak"] = max(pet.get("best_streak", 0), pet["streak"])
    events = ["recovered"] if red_since is not None and pet["meals"] > 1 else []
    if before == "egg":
        return [*events, "hatched"]
    if stage(pet["meals"]) != before:
        return [*events, "grew"]
    return [*events, "ate"]


def _date(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def line(pet: dict[str, Any], now: float, events: list[str] | None = None) -> Text:
    events = events or []
    kind, happy, sick = SPECIES[pet["species"] % len(SPECIES)]
    name, meals = pet["name"], pet["meals"]
    fed = f"{meals} meal{'s' * (meals != 1)}"
    if pet.get("died"):
        text = Text.assemble("🪦 ", (f"{name} the {kind}", "bold"), (f" · {fed} · ", "dim"))
        text.append(f"{_date(pet['born'])} – {_date(pet['died'])} · a week of red", style="dim")
        if "died" in events:
            text.append("  💀 died today", style="bold red")
        else:
            text.append("  · pytest --glow-adopt to start over", style="dim")
        return text
    if meals == 0:
        return Text.assemble("🥚 ", (name, "bold"), (" · an egg · hatches on the first green run", "dim"))
    red_since = pet.get("red_since")
    if red_since is not None:
        left = min(max(DIES_AFTER - (now - red_since), 0), DIES_AFTER)  # red_since is rounded: maybe ahead of now
        hearts = _hearts(pet, now)
        text = Text.assemble((sick, "bold #f87171"), "  ", (name, "bold"), (" is sick ", "red"))
        text.append("♥" * hearts, style="#f87171")
        text.append("♡" * (HEARTS - hearts), style="grey37")
        days = math.ceil(left / 86400)
        text.append(f" · dies in {days} day{'s' * (days != 1)} without a green run", style="red")
        return text
    grown = stage(meals)
    text = Text.assemble((happy, "bold #fde68a"), "  ", (name, "bold"), (f" the {grown} {kind} ", "dim"))
    text.append("♥" * HEARTS, style="#f472b6")
    text.append(f" · {fed}", style="dim")
    if "hatched" in events:
        text.append("  🐣 hatched!", style="bold #fde68a")
    elif "grew" in events:
        text.append("  ✨ ", style="bold")
        text.append_text(render.gradient_text(f"grew up: a {grown} now", render.GRADIENTS["glow"]))
    elif "recovered" in events:
        text.append("  🩹 better now", style="bold green")
    elif "ate" in events:
        text.append("  · ate a green run 😋", style="dim")
    return text


def _state(pet: dict[str, Any]) -> str:
    if pet.get("died"):
        return "dead"
    if not pet["meals"]:
        return "egg"
    return "sick" if pet.get("red_since") is not None else "happy"


def art(pet: dict[str, Any]) -> list[str]:
    state = _state(pet)
    if state in ("dead", "egg"):
        lines = list(GRAVE if state == "dead" else EGG)
        hat = ""
    else:
        species = pet["species"] % len(SPECIES)
        eye, mouth = EYES[state], MOUTHS[state][species]
        lines = [line.replace("{e}", eye).replace("{m}", mouth) for line in ART[species]]
        hat = HATS.get(stage(pet["meals"]), "")
    lines = [hat, *lines] if hat else ["", *lines]
    width = max(len(line.rstrip()) for line in lines)
    return [line.rstrip().ljust(width) for line in lines]


def _next_stage(meals: int) -> tuple[str, int, int] | None:
    """The stage after this one: its name, the meals it takes, and where this one started."""
    for (at, _), (then, name) in itertools.pairwise(STAGES):
        if at <= meals < then:
            return name, then, at
    return None


def _mood(pet: dict[str, Any], now: float) -> str:
    state = _state(pet)
    if state == "dead":
        return "it waited a week for a green run"
    moods = MOODS[state]
    return moods[zlib.crc32(f"{pet['name']}/{_date(now)}".encode()) % len(moods)]  # the same all day


def _hearts(pet: dict[str, Any], now: float) -> int:
    red_since = pet.get("red_since")
    if red_since is None:
        return HEARTS
    left = min(max(DIES_AFTER - (now - red_since), 0), DIES_AFTER)  # red_since is rounded: maybe ahead of now
    return max(math.ceil(left / DIES_AFTER * HEARTS), 1)


def _status(pet: dict[str, Any], now: float, events: list[str]) -> Text:
    state = _state(pet)
    if state == "dead":
        text = Text(f"died {_date(pet['died'])}, after a week of red", style="dim")
        if "died" in events:
            text.append("  💀 today", style="bold red")
        return text
    if state == "egg":
        return Text("an egg · hatches on the first green run", style="dim")
    hearts = _hearts(pet, now)
    text = Text("♥" * hearts, style="#f87171" if state == "sick" else "#f472b6")
    text.append("♡" * (HEARTS - hearts), style="grey37")
    if state == "sick":
        left = min(max(DIES_AFTER - (now - pet["red_since"]), 0), DIES_AFTER)
        days = math.ceil(left / 86400)
        text.append(f"  sick · dies in {days} day{'s' * (days != 1)} without a green run", style="red")
    else:
        text.append("  healthy", style="green")
    for event, said, style in (
        ("hatched", "🐣 hatched!", "bold #fde68a"),
        ("grew", "✨ grew up!", "bold #fde68a"),
        ("recovered", "🩹 better now", "bold green"),
        ("ate", "ate a green run 😋", "dim"),
    ):
        if event in events:
            text.append(f"  · {said}", style=style)
            break
    return text


def card(pet: dict[str, Any], now: float, events: list[str] | None = None) -> Panel:
    """The pet's own box under the verdict: big, with everything there is to know about it."""
    state = _state(pet)
    kind = SPECIES[pet["species"] % len(SPECIES)][0]
    color = {"dead": "grey50", "egg": "#e5e7eb", "sick": "#f87171"}.get(state, COLORS[pet["species"] % len(COLORS)])
    drawing = Text("\n".join(art(pet)), style=f"bold {color}", no_wrap=True)

    info = Table.grid(padding=(0, 1))
    info.add_column(no_wrap=True)
    info.add_column()
    what = {"egg": "egg", "dead": kind}.get(state, f"{stage(pet['meals'])} {kind}")
    info.add_row("", Text.assemble((pet["name"], "bold"), (f"  the {what}", "dim")))
    info.add_row("", _status(pet, now, events or []))
    born = pet["born"]
    end = pet.get("died") or now
    days = int((end - born) // 86400)
    info.add_row("🎂", Text(f"{days} day{'s' * (days != 1)} old · born {_date(born)}", style="dim"))
    meals = pet["meals"]
    fed = Text(f"{meals} meal{'s' * (meals != 1)}", style="dim")
    after = _next_stage(meals)
    if after is not None and state != "dead":
        name, then, since = after
        done = (meals - since) / (then - since)
        cells = 12
        filled = round(done * cells)
        fed.append("  ")
        fed.append("▰" * filled, style=color)
        fed.append("▱" * (cells - filled), style="grey37")
        fed.append(f"  {name} in {then - meals}", style="dim")
    elif state != "dead":
        fed.append("  · fully grown", style="dim")
    info.add_row("🍖", fed)
    if state != "egg":
        streak, best, sick = pet.get("streak", 0), pet.get("best_streak", 0), pet.get("sick_times", 0)
        record = Text(f"{streak} green in a row · best {best}", style="dim")
        if sick:
            record.append(f" · sick {sick} time{'s' * (sick != 1)}", style="dim")
        info.add_row("🔥", record)
    info.add_row("💭", Text(_mood(pet, now), style="italic"))
    graves = pet.get("graves", [])
    if graves:
        names = ", ".join(g["name"] for g in graves[-3:])
        info.add_row("🪦", Text(f"{len(graves)} before it: {names}", style="dim"))

    body = Table.grid(padding=(0, 2))
    body.add_column(no_wrap=True)
    body.add_column()
    body.add_row(drawing, info)
    return Panel(
        body,
        title=Text(" 🐾 pet ", style="dim"),
        title_align="left",
        border_style=color,
        box=box.ROUNDED,
        expand=False,
        padding=(0, 1),
    )


def main(root: str, name: str | None) -> int:
    """``pytest --glow-adopt [NAME]``: the one and only time it asks."""
    console = Console(highlight=False)
    existing = load(root)
    if existing is not None and not existing.get("died"):
        console.print(Text.assemble("  ", line(existing, time.time())))
        console.print(Text(f"  {existing['name']} already lives here. it's yours, for good.", style="dim"))
        return 0
    project = os.path.basename(os.path.realpath(root))
    console.print(Text.assemble("\n  🥚 ", ("a pet for ", "bold"), (project, "bold magenta")))
    for term in CONTRACT:
        console.print(Text(f"     · {term}", style="dim"))
    if not name:
        if not sys.stdin.isatty():
            console.print(Text("  name it to sign: pytest --glow-adopt NAME", style="yellow"))
            return 4
        try:
            name = input("\n  name it to sign, or press enter to back out: ").strip()
        except (EOFError, KeyboardInterrupt):
            name = ""
        if not name:
            console.print(Text("  backed out. no pet. no hard feelings.", style="dim"))
            return 0
    pet = adopt(root, name[:24])
    console.print()
    console.print(Text.assemble("  ", line(pet, time.time())))
    console.print(Text(f"  signed. {pet['name']} is yours now.", style="bold magenta"))
    return 0
