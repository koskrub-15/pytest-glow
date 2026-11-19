"""Readable diffs for failed `==` assertions: what differs, not what pytest had room to print."""

from __future__ import annotations

import dataclasses
import difflib
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

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

    @property
    def summary(self) -> str:
        if not self.changes:
            return ""
        more = len(self.changes) - 1
        return self.changes[0] + (f"  (+{more} more)" if more else "")

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
