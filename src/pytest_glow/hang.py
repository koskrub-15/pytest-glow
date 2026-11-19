"""Where a long-running test is right now: read off the main thread's stack while it runs."""

from __future__ import annotations

import linecache
import os
import sys
from dataclasses import dataclass
from types import FrameType

from rich.text import Text

HANG = 3.0  # seconds before a running test shows where it is


@dataclass
class Spot:
    path: str
    line: int
    function: str
    source: str


def _internal(path: str) -> bool:
    parts = path.split(os.sep)
    return "_pytest" in parts or "pluggy" in parts or "pytest_glow" in parts


def _spot(frame: FrameType) -> Spot:
    path, line = frame.f_code.co_filename, frame.f_lineno
    return Spot(path, line, frame.f_code.co_name, linecache.getline(path, line).strip())


def stuck_at(frame: FrameType | None, root: str) -> tuple[Spot | None, Spot | None]:
    """(the innermost frame of the project's own code, the innermost frame of all when it's elsewhere)."""
    innermost = mine = None
    while frame is not None:
        path = frame.f_code.co_filename
        if not _internal(path):
            if innermost is None:
                innermost = frame
            if mine is None and path.startswith(root + os.sep) and "site-packages" not in path.split(os.sep):
                mine = frame
                break
        frame = frame.f_back
    if mine is None:
        return (_spot(innermost), None) if innermost is not None else (None, None)
    return _spot(mine), (_spot(innermost) if innermost is not mine else None)


def thread_frame(ident: int | None) -> FrameType | None:
    return sys._current_frames().get(ident) if ident is not None else None


def short_path(path: str, here: str) -> str:
    """Relative to where pytest was started, else from site-packages, else just the file name."""
    if path.startswith(here + os.sep):
        return os.path.relpath(path, here)
    parts = path.split(os.sep)
    if "site-packages" in parts:
        return "/".join(parts[parts.index("site-packages") + 1 :])
    return os.path.basename(path)


def describe(spots: tuple[Spot | None, Spot | None], here: str) -> Text | None:
    mine, deeper = spots
    if mine is None:
        return None
    text = Text.assemble(
        ("⏳ ", "yellow"),
        (f"{short_path(mine.path, here)}:{mine.line}", "bold yellow"),
        (f" {mine.function}", "dim"),
    )
    if mine.source:
        text.append(f"  {mine.source}", style="italic")
    if deeper is not None:
        text.append(f"  → {short_path(deeper.path, here)}:{deeper.line} {deeper.function}", style="dim")
    return text
