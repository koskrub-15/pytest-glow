"""Small rendering helpers shared by the live view and the final summary."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable

from rich.style import Style
from rich.text import Text

# category -> (glyph, style, label)
OUTCOMES: dict[str, tuple[str, str, str]] = {
    "passed": ("✓", "green", "passed"),
    "failed": ("✗", "red", "failed"),
    "error": ("E", "bold red", "error"),
    "skipped": ("↷", "yellow", "skipped"),
    "xfailed": ("x", "magenta", "xfailed"),
    "xpassed": ("★", "yellow", "xpassed"),
    "rerun": ("↻", "yellow", "rerun"),
}
ORDER = ["passed", "failed", "error", "skipped", "xfailed", "xpassed", "rerun"]
SEVERITY = ["passed", "xfailed", "skipped", "rerun", "xpassed", "failed", "error"]
FAILING = ("failed", "error")
SPARKS = "▁▂▃▄▅▆▇█"


def glyph(category: str) -> str:
    return OUTCOMES.get(category, ("•", "", ""))[0]


def style(category: str) -> str:
    return OUTCOMES.get(category, ("", "cyan", ""))[1]


def label(category: str, n: int = 1) -> str:
    word = OUTCOMES.get(category, ("", "", category))[2] or category
    return word + "s" if n != 1 and word in ("error", "warning", "collection error") else word


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain(text: str) -> str:
    """pytest colours assertion diffs itself; rich wants plain text."""
    return _ANSI.sub("", text)


def worst(categories: Iterable[str]) -> str:
    rank = {c: i for i, c in enumerate(SEVERITY)}
    return max(categories, key=lambda c: rank.get(c, 0), default="passed")


def fmt_dur(seconds: float) -> str:
    if seconds < 0.001:
        return "<1ms"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def fmt_clock(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def test_name(nodeid: str) -> str:
    return nodeid.split("::", 1)[1] if "::" in nodeid else nodeid


def path_text(path: str, width: int | None = None) -> Text:
    if width is not None and len(path) > width:
        path = "…" + path[-(width - 1) :]
    head, sep, tail = path.rpartition("/")
    text = Text.assemble((head + sep, "dim"), (tail, "bold"))
    if width is not None:
        text.pad_right(width - len(path))
    return text


def nodeid_text(nodeid: str) -> Text:
    path, sep, name = nodeid.partition("::")
    return Text.assemble(path_text(path), (sep, "dim"), (name, "bold"))


def linked(text: Text, url: str | None) -> Text:
    """``text`` as a clickable link (OSC 8) when there's a URL."""
    if url:
        text.stylize(Style(link=url))
    return text


def counts_text(counts: Counter, *, compact: bool = True, extra: dict[str, int] | None = None) -> Text:
    parts = []
    for cat in ORDER + sorted(set(counts) - set(ORDER)):
        n = counts.get(cat, 0)
        if not n:
            continue
        if compact:
            parts.append(Text(f"{glyph(cat)}{n}", style=style(cat)))
        else:
            parts.append(Text.assemble((str(n), f"bold {style(cat)}"), (f" {label(cat, n)}", "dim")))
    for name, (n, st) in (extra or {}).items():
        if n:
            parts.append(Text.assemble((str(n), f"bold {st}"), (f" {label(name, n)}", "dim")))
    return join(parts, Text(" " if compact else " · ", style="dim"))


def strip(categories: list[str], total: int, width: int, ages: list[float] | None = None) -> Text:
    """A segmented bar, one cell per test (or per bucket of tests when there are many).

    With ``ages`` (seconds since each test finished), fresh cells flash white and fade into their colour.
    """
    total = max(total, len(categories), 1)
    cells = min(total, width)
    text = Text()
    for i in range(cells):
        lo, hi = i * total // cells, max((i + 1) * total // cells, i * total // cells + 1)
        bucket = categories[lo:hi]
        if not bucket:
            text.append("━", style=_TRACK)
        else:
            cat = worst(bucket)
            age = min(ages[lo:hi]) if ages and ages[lo:hi] else FLASH
            if age < FLASH and cat in HEX:
                text.append("━", style=f"bold {blend(HEX[cat], _WHITE, 1 - age / FLASH)}")
            else:
                text.append("━", style=HEX.get(cat, style(cat)))
    text.pad_right(width - cells)
    return text


def proportion_bar(counts: Counter, width: int) -> Text:
    total = sum(counts.values())
    text = Text()
    if total == 0 or width <= 0:
        return Text("━" * max(width, 0), style="grey30")
    cats = [c for c in SEVERITY if counts.get(c)] + [c for c in counts if c not in SEVERITY and counts[c]]
    exact = {c: counts[c] * width / total for c in cats}
    sizes = {c: max(1, int(exact[c])) for c in cats}
    while sum(sizes.values()) < width:
        c = max(cats, key=lambda c: exact[c] - sizes[c])
        sizes[c] += 1
    while sum(sizes.values()) > width:
        c = max((c for c in cats if sizes[c] > 1), key=lambda c: sizes[c] - exact[c])
        sizes[c] -= 1
    for c in cats:
        text.append("━" * sizes[c], style=HEX.get(c, style(c)))
    return text


def sparkline(runs: list[dict]) -> Text:
    text = Text()
    if not runs:
        return text
    top = max(r.get("d", 0) for r in runs) or 1
    for i, run in enumerate(runs):
        level = min(len(SPARKS) - 1, int(run.get("d", 0) / top * (len(SPARKS) - 1) + 0.5))
        st = "green" if run.get("ok") else "red"
        if i == len(runs) - 1:
            st = f"bold {st}"
        text.append(SPARKS[level], style=st)
    return text


def outcome_trail(outcomes: str) -> Text:
    codes = {"P": "passed", "F": "failed", "E": "error", "S": "skipped", "x": "xfailed", "X": "xpassed"}
    text = Text()
    for c in outcomes:
        cat = codes.get(c, "")
        text.append(glyph(cat) if cat else "?", style=style(cat) if cat else "dim")
    return text


_LOCATION = re.compile(r"^\S+:\d+: ")
_XDIST_WORKER = re.compile(r"^\[gw\d+\] ")


def longrepr_text(text: str) -> Text:
    """Light highlighting for pytest's plain-text failure output."""
    out = Text()
    for line in plain(text).splitlines():
        if _XDIST_WORKER.match(line):
            continue
        if line.startswith("E "):
            out.append(line, style="red")
        elif line.startswith(">"):
            out.append(line, style="bold yellow")
        elif _LOCATION.match(line):
            out.append(line, style="cyan")
        elif set(line.strip()) <= {"_", " "} and line.strip():
            out.append(line, style="dim")
        else:
            out.append(line)
        out.append("\n")
    out.rstrip()
    return out


def crash_message(report) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    message = getattr(crash, "message", None)
    if not message:
        lines = [ln for ln in str(report.longreprtext).splitlines() if ln.strip()]
        message = lines[-1] if lines else ""
    message = plain(message).strip()
    return message.splitlines()[0] if message else ""


def _is_internal(filename: str) -> bool:
    parts = filename.split(os.sep)
    return "_pytest" in parts or "pluggy" in parts


def shorten_paths(traceback, root: str) -> None:
    """Show frames relative to where pytest was started instead of as absolute paths.

    rich reads the source through the same path when it renders, so this only
    happens while the working directory is still that root.
    """
    if os.getcwd() != root:
        return
    for stack in traceback.trace.stacks:
        for frame in stack.frames:
            if frame.filename.startswith(root + os.sep):
                frame.filename = os.path.relpath(frame.filename, root)


def rich_traceback(excinfo, width: int, *, brief: bool = False):
    """A rich traceback with pytest/pluggy frames trimmed and assertion temporaries hidden.

    ``brief`` keeps only the first line of the error, for when a diff explains the rest.
    """
    import _pytest
    import pluggy
    from rich.traceback import Traceback

    tb = excinfo.tb
    while tb is not None and _is_internal(tb.tb_frame.f_code.co_filename):
        tb = tb.tb_next
    trace = Traceback.extract(
        excinfo.type, excinfo.value, tb or excinfo.tb, show_locals=True, locals_max_length=6, locals_max_string=60
    )
    for stack in trace.stacks:
        stack.exc_value = plain(stack.exc_value)
        for frame in stack.frames:
            if frame.locals:
                frame.locals = {k: v for k, v in frame.locals.items() if not k.startswith("@")}
    if brief and trace.stacks:
        trace.stacks[0].exc_value = trace.stacks[0].exc_value.split("\n", 1)[0]
    return Traceback(
        trace,
        width=width,
        code_width=min(width - 4, 100),
        extra_lines=2,
        show_locals=True,
        locals_max_length=6,
        locals_max_string=60,
        word_wrap=True,
        suppress=[_pytest, pluggy],
        max_frames=8,
    )


# -- glow effects: truecolor gradients (rich downgrades them on 256/16-colour terminals) --

GRADIENTS: dict[str, tuple[str, ...]] = {
    "glow": ("#ff4fd8", "#a855f7", "#22d3ee"),
    "green": ("#16a34a", "#22c55e", "#a3e635"),
    "red": ("#dc2626", "#f43f5e", "#fb923c"),
    "yellow": ("#ca8a04", "#eab308", "#fb923c"),
    "cyan": ("#0891b2", "#22d3ee", "#a5f3fc"),
    "grey50": ("#4b5563", "#9ca3af"),
    "fire": ("#facc15", "#f97316", "#ef4444"),
    "gold": ("#fef3c7", "#facc15", "#f59e0b", "#fde68a"),
}


def combo_stops(n: int) -> tuple[str, ...]:
    """Combos heat up: cyan, green, neon, then fire."""
    return GRADIENTS["cyan" if n < 25 else "green" if n < 50 else "glow" if n < 100 else "fire"]


HEX = {
    "passed": "#22c55e",
    "failed": "#ef4444",
    "error": "#ef4444",
    "skipped": "#eab308",
    "xfailed": "#d946ef",
    "xpassed": "#eab308",
    "rerun": "#eab308",
}
_WHITE = (255, 255, 255)
_TRACK = "#3b3b4a"
FLASH = 0.6  # seconds a freshly finished test glows in the live strip


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _hex(rgb: tuple[float, ...]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def blend(a: str, b: str | tuple[int, int, int], t: float) -> str:
    ra, rb = _rgb(a), (_rgb(b) if isinstance(b, str) else b)
    t = max(0.0, min(1.0, t))
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb, strict=True)))


def gradient_at(stops: tuple[str, ...], t: float) -> str:
    if len(stops) == 1:
        return stops[0]
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return blend(stops[i], stops[i + 1], t - i)


def gradient_text(text: str, stops: tuple[str, ...], style: str = "bold", *, background: bool = False) -> Text:
    out = Text()
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        color = gradient_at(stops, i / n)
        out.append(ch, style=f"{style} #0b0b10 on {color}" if background else f"{style} {color}")
    return out


def join(parts: list[Text], sep: Text) -> Text:
    """Text.join gives the result the separator's style; this keeps every part's own."""
    out = Text()
    for i, part in enumerate(parts):
        if i:
            out.append_text(sep)
        out.append_text(part)
    return out


def glow_bar(completed: float, total: float, width: int, stops: tuple[str, ...], now: float | None = None) -> Text:
    """A gradient bar; given a clock, a highlight sweeps along the filled part."""
    width = max(width, 1)
    cells = width * min(max(completed / total, 0.0), 1.0) if total else 0.0
    full = int(cells)
    half = cells - full >= 0.5 and full < width
    center = None
    if now is not None and full:
        span = full + 16
        center = (now * 45) % span - 8
    text = Text()
    for i in range(full):
        color = gradient_at(stops, i / max(width - 1, 1))
        if center is not None and abs(i - center) < 6:
            color = blend(color, _WHITE, (1 - abs(i - center) / 6) * 0.65)
        text.append("━", style=color)
    if half:
        text.append("╸", style=gradient_at(stops, full / max(width - 1, 1)))
    rest = width - full - (1 if half else 0)
    if rest:
        text.append(("╺" if half else "━") + "━" * (rest - 1), style=_TRACK)
    return text


class GlowBar:
    """glow_bar as a renderable that fills whatever width a table column gives it."""

    def __init__(self, completed: float, total: float, stops: tuple[str, ...], now: float | None = None) -> None:
        self.completed, self.total, self.stops, self.now = completed, total, stops, now

    def __rich_measure__(self, console, options):
        from rich.measure import Measurement

        return Measurement(4, options.max_width)

    def __rich_console__(self, console, options):
        yield glow_bar(self.completed, self.total, options.max_width, self.stops, self.now)


class GhostBar:
    """Where the personal best run was at this point: a faint trail, and the ghost at its head."""

    def __init__(self, completed: float, total: float) -> None:
        self.completed, self.total = completed, total

    def __rich_measure__(self, console, options):
        from rich.measure import Measurement

        return Measurement(4, options.max_width)

    def __rich_console__(self, console, options):
        width = max(options.max_width, 3)
        at = round((width - 2) * min(max(self.completed / self.total, 0.0), 1.0)) if self.total else 0
        trail = Text()
        for i in range(at):
            trail.append("╌", style=blend(_TRACK, "#9ca3af", i / max(width - 3, 1)))
        trail.append("👻")
        trail.append(" " * (width - at - 2))
        yield trail


def fade_rule(title: str, stops: tuple[str, ...], width: int) -> Text:
    """A section heading: a gradient title and a line that fades into the background."""
    head = Text("▍", style=stops[0]) + gradient_text(f" {title} ", stops)
    rest = max(width - len(head), 0)
    for i in range(rest):
        head.append("─", style=blend(stops[-1], _TRACK, i / max(rest - 1, 1)))
    return head


class GlowPanel:
    """A rounded panel whose border is a diagonal gradient, with an optional title on the top edge."""

    def __init__(self, body, stops: tuple[str, ...], title: Text | None = None) -> None:
        self.body, self.stops, self.title = body, stops, title

    def __rich_console__(self, console, options):
        from rich.segment import Segment
        from rich.style import Style

        width = options.max_width
        lines = console.render_lines(self.body, options.update_width(max(width - 4, 1)), pad=True)
        height = len(lines) + 2

        def color(x: int, y: int) -> Style:
            return Style.parse(gradient_at(self.stops, 0.75 * x / max(width - 1, 1) + 0.25 * y / max(height - 1, 1)))

        def edge(left: str, right: str, y: int) -> Text:
            text = Text()
            text.append(left, style=color(0, y))
            for x in range(1, width - 1):
                text.append("─", style=color(x, y))
            text.append(right, style=color(width - 1, y))
            return text

        top = edge("╭", "╮", 0)
        if self.title is not None and len(self.title) < width - 6:
            start = width - len(self.title) - 3
            top = top[:start] + self.title + top[start + len(self.title) :]
        yield top
        for y, line in enumerate(lines, start=1):
            yield Segment("│ ", color(0, y))
            yield from line
            yield Segment(" │", color(width - 1, y))
            yield Segment.line()
        yield edge("╰", "╯", height - 1)


def spark(values: list[float], stops: tuple[str, ...]) -> Text:
    """A sparkline of plain values; the last (current) one is drawn bold."""
    text = Text()
    if not values:
        return text
    lo, hi = min(values), max(values)
    for i, v in enumerate(values):
        t = (v - lo) / (hi - lo) if hi > lo else 0.5
        st = gradient_at(stops, t)
        text.append(SPARKS[round(t * (len(SPARKS) - 1))], style=f"bold {st}" if i == len(values) - 1 else st)
    return text


CONFETTI = "✦✧•*·+°"


class Confetti:
    """A few bursts of particles thrown up from below, falling back under gravity."""

    def __init__(self, width: int, height: int = 6, seed: int | None = None) -> None:
        import random

        rnd = random.Random(seed)
        self.width, self.height = width, height
        colors = [*GRADIENTS["glow"], *GRADIENTS["green"], "#facc15", "#fb923c"]
        self.particles = []
        for burst in range(4):
            x0 = rnd.uniform(0.15, 0.85) * width
            delay = burst * 0.12
            for _ in range(18):
                self.particles.append(
                    (
                        x0,
                        delay,
                        rnd.uniform(-28, 28),  # sideways speed, cells/s
                        rnd.uniform(14, 24),  # upward speed, rows/s
                        rnd.choice(CONFETTI),
                        rnd.choice(colors),
                    )
                )

    def frame(self, t: float) -> Text:
        grid: dict[tuple[int, int], tuple[str, str]] = {}
        for x0, delay, vx, vy, ch, color in self.particles:
            age = t - delay
            if age < 0:
                continue
            x = round(x0 + vx * age)
            y = round(self.height - (vy * age - 30 * age * age))  # rows from the top
            if 0 <= x < self.width and 0 <= y < self.height:
                fade = min(max((age - 0.5) / 0.5, 0.0), 1.0)
                grid[(y, x)] = (ch, blend(color, "#3b3b4a", fade))
        text = Text()
        for y in range(self.height):
            for x in range(self.width):
                ch, color = grid.get((y, x), (" ", ""))
                text.append(ch, style=color)
            if y < self.height - 1:
                text.append("\n")
        return text


GLITCH = 0.6  # seconds the live view comes apart when a combo breaks
GLITCH_CHARS = "▓▒░█▚▞▙▟#%&@$"
_TEARS = ("#dc2626", "#22d3ee", "#e879f9")


def glitch(text: Text, amount: float, rnd) -> Text:
    """``text`` with some of its characters corrupted, a colour tear or two, and shaken sideways."""
    chars = [rnd.choice(GLITCH_CHARS) if c not in " \n" and rnd.random() < amount else c for c in text.plain]
    torn = Text("".join(chars), style=text.style, end=text.end, no_wrap=text.no_wrap, overflow=text.overflow)
    for span in text.spans:
        torn.stylize(span.style, span.start, span.end)
    for _ in range(int(amount * 20)):
        start = rnd.randrange(max(len(chars), 1))
        torn.stylize(f"bold {rnd.choice(_TEARS)}", start, start + rnd.randint(2, 8))
    return Text(" " * rnd.choice((0, 0, 1, 2))) + torn


def skill_issue(combo: int, age: float) -> Text:
    """The banner a broken combo gets: the stutter first, then the diagnosis, flickering."""
    word = " C-C-C-COMBO BREAKER " if age < GLITCH / 2 else " S K I L L   I S S U E "
    flicker = int(age * 16) % 2
    return Text.assemble(
        "  ",
        ("▓▒░", "#dc2626"),
        (word, "bold white on #dc2626" if flicker else "bold #dc2626 on #fde68a"),
        ("░▒▓", "#dc2626"),
        (f"  ×{combo} combo, gone", "bold red"),
    )
