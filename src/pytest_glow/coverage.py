"""Coverage from pytest-cov, drawn the glow way instead of its plain-text table."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from . import render


@dataclass
class FileCoverage:
    path: str
    statements: int
    missing: list[int]
    percent: float


@dataclass
class CoverageResult:
    total: float
    files: list[FileCoverage]
    show_table: bool
    show_missing: bool
    skip_covered: bool
    fail_under: float | None
    precision: int
    notes: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.fail_under is not None and round(self.total, self.precision) < self.fail_under


def collect(config: Any) -> CoverageResult | None:
    """Read pytest-cov's finished measurement and take over its terminal output."""
    plugin = config.pluginmanager.get_plugin("_cov")
    if plugin is None or getattr(plugin, "cov_total", None) is None:
        return None
    cov = getattr(getattr(plugin, "cov_controller", None), "cov", None)
    options = getattr(plugin, "options", None)
    if cov is None or options is None:
        return None

    report = options.cov_report or {}
    files: list[FileCoverage] = []
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            outfile = os.path.join(tmp, "coverage.json")
            cov.json_report(outfile=outfile, ignore_errors=True)
            with open(outfile, encoding="utf-8") as f:
                data = json.load(f)
        for path, entry in sorted(data.get("files", {}).items()):
            summary = entry.get("summary", {})
            files.append(
                FileCoverage(
                    path=path.replace(os.sep, "/"),
                    statements=summary.get("num_statements", 0),
                    missing=sorted(entry.get("missing_lines", [])),
                    percent=summary.get("percent_covered", 100.0),
                )
            )
    except Exception:
        return None  # leave pytest-cov's own report alone

    result = CoverageResult(
        total=plugin.cov_total,
        files=files,
        show_table=any(k in report for k in ("term", "term-missing")),
        show_missing="term-missing" in report,
        skip_covered=isinstance(report, dict) and "skip-covered" in report.values(),
        fail_under=options.cov_fail_under or None,
        precision=getattr(options, "cov_precision", 2) or 0,
        # Keep "Coverage HTML written to dir htmlcov" and friends, drop the table.
        notes=[ln for ln in plugin.cov_report.getvalue().splitlines() if ln.startswith("Coverage ")],
    )
    plugin.cov_report = io.StringIO()
    options.cov_fail_under = None  # its pass/fail line moves into our verdict panel
    return result


def color(percent: float, fail_under: float | None = None) -> str:
    if fail_under is not None and percent < fail_under:
        return "red"
    return "green" if percent >= 90 else "yellow" if percent >= 75 else "red"


def bar(percent: float, width: int, fail_under: float | None = None) -> Text:
    filled = round(percent / 100 * width)
    if percent < 100:
        filled = min(filled, width - 1)  # an almost-full bar must still look unfinished
    stops = render.GRADIENTS[color(percent, fail_under)]
    text = Text()
    for i in range(filled):
        text.append("━", style=render.gradient_at(stops, i / max(width - 1, 1)))
    text.append("━" * (width - filled), style=render._TRACK)
    return text


def ranges(lines: list[int]) -> str:
    out: list[str] = []
    start = prev = None
    for n in lines:
        if prev is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    if start is not None:
        out.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def fmt_percent(percent: float, precision: int) -> str:
    """Rounded like coverage.py: never shows 100% or 0% unless it really is."""
    shown = round(percent, precision)
    step = 10**-precision
    if shown >= 100 and percent < 100:
        shown = 100 - step
    elif shown <= 0 < percent:
        shown = step
    return f"{shown:.{precision}f}%"
