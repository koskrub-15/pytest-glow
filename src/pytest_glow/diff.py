"""Readable diffs for failed `==` assertions: what differs, not what pytest had room to print."""

from __future__ import annotations

import dataclasses
import difflib
from dataclasses import dataclass, field
from typing import Any

import pytest
from rich.text import Span, Text

LEFT = "#f87171"
RIGHT = "#4ade80"
LEFT_HI = "bold #fecaca on #7f1d1d"
RIGHT_HI = "bold #bbf7d0 on #14532d"
CHANGED = "#facc15"
MAX_LINES = 40
MAX_REPR = 80
MAX_DEPTH = 6


@dataclass
class Diff:
    lines: list[Text] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)  # one short description per difference
    title: str = ""  # the panel's title, when it isn't left and right

    @property
    def summary(self) -> str:
        if not self.changes:
            return ""
        more = len(self.changes) - 1
        return self.changes[0] + (f"  (+{more} more)" if more else "")

    def dump(self) -> dict:
        """As plain data, to travel with a report from an xdist worker."""
        lines = [
            [line.plain, [[sp.start, sp.end, str(sp.style)] for sp in line.spans], str(line.style)]
            for line in self.lines
        ]
        return {"lines": lines, "changes": self.changes, "title": self.title}

    @classmethod
    def load(cls, data: Any) -> Diff | None:
        try:
            lines = [
                Text(plain, style=style, spans=[Span(*sp) for sp in spans]) for plain, spans, style in data["lines"]
            ]
            return cls(lines, list(data["changes"]), str(data.get("title", "")))
        except Exception:
            return None

    def render(self) -> Text:
        lines = self.lines
        if len(lines) > MAX_LINES:
            lines = [*lines[:MAX_LINES], Text(f"… {len(self.lines) - MAX_LINES} more lines", style="dim")]
        text = Text("\n").join(lines)
        text.no_wrap = True
        text.overflow = "ellipsis"
        return text


def short(value: Any, limit: int = MAX_REPR) -> str:
    try:
        r = repr(value)
    except Exception:
        r = f"<{type(value).__name__}>"
    return r if len(r) <= limit else r[: limit - 1] + "…"


def _equal(a: Any, b: Any) -> bool:
    try:
        return bool(a == b)
    except Exception:
        return False


def _fields(value: Any) -> dict | None:
    """Dataclasses and namedtuples compare like dicts of their fields."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return dict(value._asdict())
    return None


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def explain(left: Any, right: Any) -> Diff | None:
    """A diff of two unequal values, or None when there's nothing better to say than pytest does."""
    try:
        diff = Diff()
        if not _walk(left, right, diff, indent="", path="", depth=0):
            return None
        return diff if diff.lines else None
    except Exception:
        return None


def for_error(compare: tuple | None, error: BaseException) -> Diff | None:
    """The diff of a test's failed assert: ``compare`` is (op, left, right) of the last comparison pytest explained,
    which only counts when it's the assert that failed: one caught earlier (pytest.raises) mustn't be blamed."""
    if compare is None or not isinstance(error, AssertionError):
        return None
    op, left, right = compare
    if f" {op} " not in str(error).split("\n", 1)[0]:
        return None
    if op == "==":
        return explain(left, right)
    return explain_in(left, right, negated=op == "not in")


MAX_WINDOWS = 4000  # substrings of a long text tried as near misses


def explain_in(item: Any, container: Any, negated: bool = False) -> Diff | None:
    """Why `item in container` failed: the near misses when it isn't there, where it is when it shouldn't be."""
    try:
        diff = Diff(title="found, and shouldn't be" if negated else "not in there")
        if isinstance(item, str) and isinstance(container, str):
            (_found_in_text if negated else _missing_from_text)(item, container, diff)
        elif isinstance(container, (list, tuple, set, frozenset, dict)):
            (_found_in_items if negated else _missing_from_items)(item, container, diff)
        return diff if diff.lines else None
    except Exception:
        return None


def _closest_window(item: str, text: str) -> tuple[int, str, float] | None:
    """The substring of ``text`` most like ``item``: (where, substring, likeness)."""
    size = len(item)
    if not size or len(text) < 2:
        return None
    starts = range(0, max(len(text) - size, 0) + 1, max(1, (len(text) - size) // MAX_WINDOWS + 1))
    best = None
    for start in starts:
        window = text[start : start + size]
        matcher = difflib.SequenceMatcher(None, item, window, autojunk=False)
        if matcher.real_quick_ratio() < 0.6 or (best and matcher.quick_ratio() <= best[2]):
            continue
        ratio = matcher.ratio()
        if ratio >= 0.6 and (best is None or ratio > best[2]):
            blocks = [b for b in matcher.get_matching_blocks() if b.size]
            first, last = blocks[0].b, blocks[-1].b + blocks[-1].size  # without what's around the match
            best = (start + first, window[first:last], ratio)
    return best


def _missing_from_text(item: str, text: str, diff: Diff) -> None:
    near = _closest_window(item, text) if "\n" not in item else None
    if near is None:
        return
    start, window, _ = near
    a, b = _highlight(repr(item), repr(window))
    diff.lines.append(Text.assemble(("- ", LEFT), a, ("   looked for", "dim")))
    diff.lines.append(Text.assemble(("+ ", RIGHT), b, (f"   closest, at char {start}", "dim")))
    diff.changes.append(f"not in the text; closest {short(window, 30)} at char {start}")


def _found_in_text(item: str, text: str, diff: Diff) -> None:
    start = text.find(item)
    if start < 0:
        return
    count = text.count(item)
    before, after = text[max(start - 25, 0) : start], text[start + len(item) : start + len(item) + 25]
    line = Text("  ")
    line.append(("…" if start > 25 else "") + repr(before)[1:-1], style="dim")
    line.append(repr(item)[1:-1], style=LEFT_HI)
    line.append(repr(after)[1:-1] + ("…" if start + len(item) + 25 < len(text) else ""), style="dim")
    diff.lines.append(line)
    times = f", {count} times" if count > 1 else ""
    diff.changes.append(f"found at char {start}{times}")


def _candidates(container: Any) -> list[tuple[str, Any]]:
    """(label, item) of what's in the container: [i] for a sequence, the item itself for a set, dict keys."""
    if isinstance(container, (list, tuple)):
        return [(f"[{i}]", x) for i, x in enumerate(container)]
    if isinstance(container, (set, frozenset)):
        return [("", x) for x in sorted(container, key=short)]
    return [("key", x) for x in container]


def _missing_from_items(item: Any, container: Any, diff: Diff) -> None:
    items = _candidates(container)
    if not items:
        return
    if _number(item):
        numbers = [(label, x) for label, x in items if _number(x)]
        close = sorted(numbers, key=lambda pair: abs(pair[1] - item))[:3]
        if close:  # the nearest, and others only about as near
            near = max(abs(close[0][1] - item) * 10, abs(item) * 0.01)
            close = [pair for pair in close if abs(pair[1] - item) <= near]
    else:
        wanted = item if isinstance(item, str) else short(item, 1000)
        keyed = {}
        for label, x in items:
            keyed.setdefault(x if isinstance(x, str) and isinstance(item, str) else short(x, 1000), (label, x))
        names = difflib.get_close_matches(wanted, list(keyed), n=3, cutoff=0.6)
        close = [keyed[name] for name in names]
    noun = "keys" if isinstance(container, dict) else "items"
    diff.lines.append(
        Text.assemble(("- ", LEFT), (short(item), LEFT), (f"   not among the {len(items)} {noun}", "dim"))
    )
    for label, x in close:
        line = Text("  ")
        if isinstance(x, str) and isinstance(item, str):
            _, b = _highlight(repr(item), repr(x))
        else:
            b = Text(short(x), style=RIGHT)
        line.append(f"{label} " if label and label != "key" else "", style="bold")
        line.append_text(b)
        if _number(item) and _number(x):
            line.append(f"   Δ {x - item:+g}", style="dim")
        diff.lines.append(line)
    if close:
        label, x = close[0]
        where = f" {label}" if label.startswith("[") else ""
        diff.changes.append(f"not among the {len(items)} {noun}; closest{where} {short(x, 30)}")
    else:
        diff.changes.append(f"not among the {len(items)} {noun}")


def _found_in_items(item: Any, container: Any, diff: Diff) -> None:
    if isinstance(container, (list, tuple)):
        at = [i for i, x in enumerate(container) if _equal(x, item)]
        if not at:
            return
        shown = ", ".join(f"[{i}]" for i in at[:5]) + (" …" if len(at) > 5 else "")
        diff.lines.append(Text.assemble(("  ", ""), (short(item), LEFT_HI), (f"   at {shown}", "dim")))
        diff.changes.append(f"found at {shown}")
    elif isinstance(container, dict):
        diff.lines.append(Text.assemble(("  ", ""), (short(item), LEFT_HI), (": " + short(container.get(item)), "dim")))
        diff.changes.append(f"a key, with {short(container.get(item), 30)}")


def _walk(left: Any, right: Any, diff: Diff, indent: str, path: str, depth: int) -> bool:
    if depth > MAX_DEPTH:
        return False
    if _number(left) and _number(right):
        _numbers(left, right, diff, indent, path)
    elif isinstance(left, str) and isinstance(right, str):
        _strings(left, right, diff, indent, path)
    elif isinstance(left, dict) and isinstance(right, dict):
        _dicts(left, right, diff, indent, path, depth)
    elif (lf := _fields(left)) is not None and (rf := _fields(right)) is not None:
        if type(left) is not type(right):
            diff.lines.append(
                Text.assemble((indent, ""), ("type ", "dim"), _pair(type(left).__name__, type(right).__name__))
            )
            diff.changes.append(f"{path or 'type'}: {type(left).__name__} → {type(right).__name__}")
        _dicts(lf, rf, diff, indent, path, depth, fields=True)
    elif isinstance(left, (set, frozenset)) and isinstance(right, (set, frozenset)):
        _sets(left, right, diff, indent, path)
    elif isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        _sequences(left, right, diff, indent, path, depth)
    else:
        return False
    return True


def _pair(left: str, right: str) -> Text:
    return Text.assemble((left, LEFT), (" → ", "dim"), (right, RIGHT))


def _changed(diff: Diff, indent: str, label: str, left: Any, right: Any, path: str) -> None:
    line = Text.assemble((indent + "~ ", CHANGED), (label, "bold"), (": ", "dim"))
    if isinstance(left, str) and isinstance(right, str) and "\n" not in left + right:
        a, b = _highlight(repr(left), repr(right))
        line.append_text(a)
        line.append(" → ", style="dim")
        line.append_text(b)
    else:
        line.append_text(_pair(short(left), short(right)))
    diff.lines.append(line)
    diff.changes.append(f"{path}: {short(left, 30)} → {short(right, 30)}")


def _numbers(left: float, right: float, diff: Diff, indent: str, path: str) -> None:
    delta = left - right
    line = Text.assemble((indent, ""), _pair(short(left), short(right)), ("   Δ ", "dim"), (f"{delta:+g}", CHANGED))
    if right:
        line.append(f"  ({delta / abs(right) * 100:+.1f}%)", style="dim")
    diff.lines.append(line)
    diff.changes.append(f"{path + ': ' if path else ''}{short(left, 30)} ≠ {short(right, 30)}")


def _highlight(left: str, right: str) -> tuple[Text, Text]:
    """Both strings, with the characters that differ lit up."""
    a, b = Text(style=LEFT), Text(style=RIGHT)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if op == "equal":
            a.append(left[i1:i2])
            b.append(right[j1:j2])
        else:
            a.append(left[i1:i2], style=LEFT_HI)
            b.append(right[j1:j2], style=RIGHT_HI)
    return a, b


def _strings(left: str, right: str, diff: Diff, indent: str, path: str) -> None:
    where = f"{path}: " if path else ""
    if "\n" not in left and "\n" not in right:
        start = next(
            (i for i, (x, y) in enumerate(zip(left, right, strict=False)) if x != y), min(len(left), len(right))
        )
        a, b = _highlight(left, right)
        if start > 40:  # long common prefix: start near the first difference
            a, b = Text("…", style="dim") + a[start - 20 :], Text("…", style="dim") + b[start - 20 :]
        diff.lines.append(Text.assemble((indent + "- ", LEFT), a))
        diff.lines.append(Text.assemble((indent + "+ ", RIGHT), b))
        diff.changes.append(f"{where}strings differ at char {start}")
        return
    lines_l, lines_r = left.splitlines(), right.splitlines()
    first = None
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, lines_l, lines_r, autojunk=False).get_opcodes():
        if op == "equal":
            same = lines_l[i1:i2]
            if len(same) > 3:
                diff.lines.append(Text(f"{indent}  {same[0]}", style="dim"))
                diff.lines.append(Text(f"{indent}  … {len(same) - 2} identical lines", style="dim"))
                diff.lines.append(Text(f"{indent}  {same[-1]}", style="dim"))
            else:
                diff.lines.extend(Text(f"{indent}  {ln}", style="dim") for ln in same)
            continue
        first = i1 + 1 if first is None else first
        pairs = min(i2 - i1, j2 - j1) if op == "replace" else 0
        for k in range(pairs):
            a, b = _highlight(lines_l[i1 + k], lines_r[j1 + k])
            diff.lines.append(Text.assemble((indent + "- ", LEFT), a))
            diff.lines.append(Text.assemble((indent + "+ ", RIGHT), b))
        diff.lines.extend(Text(f"{indent}- {ln}", style=LEFT) for ln in lines_l[i1 + pairs : i2])
        diff.lines.extend(Text(f"{indent}+ {ln}", style=RIGHT) for ln in lines_r[j1 + pairs : j2])
    diff.changes.append(f"{where}text differs from line {first or 1}")


def _dicts(left: dict, right: dict, diff: Diff, indent: str, path: str, depth: int, fields: bool = False) -> None:
    same = 0
    for key in [*left, *(k for k in right if k not in left)]:
        label = key if fields else short(key, 40)
        name = key if isinstance(key, str) and key.isidentifier() else short(key, 40)
        where = f"{path}.{name}" if path else name
        if key in left and key in right:
            a, b = left[key], right[key]
            if _equal(a, b):
                same += 1
            elif _nests(a, b):
                diff.lines.append(Text.assemble((indent + "~ ", CHANGED), (label, "bold")))
                _walk(a, b, diff, indent + "    ", where, depth + 1)
            else:
                _changed(diff, indent, label, a, b, where)
        elif key in left:
            diff.lines.append(
                Text.assemble((indent + "- ", LEFT), (label, f"bold {LEFT}"), (": " + short(left[key]), LEFT))
            )
            diff.changes.append(f"{where} only on the left")
        else:
            diff.lines.append(
                Text.assemble((indent + "+ ", RIGHT), (label, f"bold {RIGHT}"), (": " + short(right[key]), RIGHT))
            )
            diff.changes.append(f"{where} only on the right")
    if same:
        noun = "field" if fields else "key"
        diff.lines.append(Text(f"{indent}  … {same} identical {noun}{'' if same == 1 else 's'}", style="dim"))


def _nests(a: Any, b: Any) -> bool:
    """Worth a nested diff rather than a one-line left → right."""
    if isinstance(a, dict) and isinstance(b, dict):
        return True
    if _fields(a) is not None and _fields(b) is not None:
        return True
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(short(a, 1000)) + len(short(b, 1000)) > 60
    if isinstance(a, str) and isinstance(b, str):
        return "\n" in a + b
    return False


def _sets(left: set, right: set, diff: Diff, indent: str, path: str) -> None:
    where = f"{path}: " if path else ""
    gone, new = left - right, right - left
    for item in sorted(gone, key=short)[:20]:
        diff.lines.append(Text(f"{indent}- {short(item)}", style=LEFT))
    for item in sorted(new, key=short)[:20]:
        diff.lines.append(Text(f"{indent}+ {short(item)}", style=RIGHT))
    if left & right:
        diff.lines.append(Text(f"{indent}  … {len(left & right)} in both", style="dim"))
    diff.changes.append(f"{where}{len(gone)} only on the left, {len(new)} only on the right")


def _sequences(left, right, diff: Diff, indent: str, path: str, depth: int) -> None:
    if len(left) != len(right):
        diff.lines.append(Text.assemble((indent, ""), ("length ", "dim"), _pair(str(len(left)), str(len(right)))))
    reprs_l, reprs_r = [short(x, 1000) for x in left], [short(x, 1000) for x in right]
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, reprs_l, reprs_r, autojunk=False).get_opcodes():
        if op == "equal":
            n = i2 - i1
            diff.lines.append(Text(f"{indent}  … {n} identical {'item' if n == 1 else 'items'}", style="dim"))
            continue
        pairs = min(i2 - i1, j2 - j1) if op == "replace" else 0
        for k in range(pairs):
            a, b, where = left[i1 + k], right[j1 + k], f"{path}[{i1 + k}]"
            if _nests(a, b):
                diff.lines.append(Text.assemble((indent + "~ ", CHANGED), (f"[{i1 + k}]", "bold")))
                _walk(a, b, diff, indent + "    ", where, depth + 1)
            else:
                _changed(diff, indent, f"[{i1 + k}]", a, b, where)
        for i in range(i1 + pairs, i2):
            diff.lines.append(
                Text.assemble((f"{indent}- ", LEFT), (f"[{i}]", f"bold {LEFT}"), (" " + short(left[i]), LEFT))
            )
            diff.changes.append(f"{path}[{i}] only on the left")
        for j in range(j1 + pairs, j2):
            diff.lines.append(
                Text.assemble((f"{indent}+ ", RIGHT), (f"[{j}]", f"bold {RIGHT}"), (" " + short(right[j]), RIGHT))
            )
            diff.changes.append(f"{path}[{j}] only on the right")
    if len(left) != len(right):
        # last: the items that changed say more than the length does
        diff.changes.append(f"{path + ': ' if path else ''}length {len(left)} → {len(right)}")


OPS = ("==", "in", "not in")  # the comparisons diffed
REPORT_ATTR = "glow_diff"  # the report attribute a worker's diff travels in: not a user property, kept out of junitxml


class Recorder:
    """On an xdist worker: diffs a failed assert there, where its operands are, and sends it along with the report."""

    def __init__(self) -> None:
        self._compare: tuple | None = None

    def pytest_runtest_logstart(self) -> None:
        self._compare = None

    def pytest_assertrepr_compare(self, op: str, left: Any, right: Any) -> None:
        if op in OPS:
            self._compare = (op, left, right)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, call: Any):
        report = yield
        compare, self._compare = self._compare, None
        if report.failed and call.excinfo is not None:
            found = for_error(compare, call.excinfo.value)
            if found is not None:
                setattr(report, REPORT_ATTR, found.dump())
        return report


def from_report(report: Any) -> Diff | None:
    data = getattr(report, REPORT_ATTR, None)
    return Diff.load(data) if data else None
