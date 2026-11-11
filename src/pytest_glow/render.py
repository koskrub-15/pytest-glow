"""Small rendering helpers shared by the live view and the final summary."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable

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
    return Text(" " if compact else " · ", style="dim").join(parts)


def strip(categories: list[str], total: int, width: int) -> Text:
    """A segmented bar, one cell per test (or per bucket of tests when there are many)."""
    total = max(total, len(categories), 1)
    cells = min(total, width)
    text = Text()
    for i in range(cells):
        lo, hi = i * total // cells, max((i + 1) * total // cells, i * total // cells + 1)
        bucket = categories[lo:hi]
        if not bucket:
            text.append("━", style="grey30")
        else:
            text.append("━", style=style(worst(bucket)))
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
        text.append("━" * sizes[c], style=style(c))
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


def rich_traceback(excinfo, width: int):
    """A rich traceback with pytest/pluggy frames trimmed and assertion temporaries hidden."""
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
