"""pytest --glow-graph: the project as a graph, tests and the files they run code from, in the browser.

Built from --glow-affected's map (which files each test runs code from) and glow's history (how each test has
been doing). One self-contained HTML file, no network: it opens on a plane too.
"""

from __future__ import annotations

import json
import os
import statistics
from importlib import resources
from typing import Any

from . import affected
from .history import FAILING, History, is_flaky

MAX_TESTS = 4000  # past this, the browser gets the tests grouped by file only


def _status(outcomes: str) -> str:
    if not outcomes:
        return "unknown"
    if outcomes[-1] in FAILING:
        return "failing"
    if is_flaky(outcomes):
        return "flaky"
    return {"P": "passed", "S": "skipped", "x": "skipped", "X": "passed"}.get(outcomes[-1], "unknown")


def build(stored: dict, history: History, project: str) -> dict[str, Any]:
    """What the page draws: files, tests, and which test ran code from which file."""
    mapped: dict[str, dict] = stored.get("tests", {}) if isinstance(stored, dict) else {}
    nodeids = list(mapped) or list(history.tests)  # no map yet: the tests, by the file they're in
    files: dict[str, int] = {}
    tests, links = [], []
    for nodeid in nodeids[:MAX_TESTS]:
        entry = history.tests.get(nodeid, {})
        durations = entry.get("d", [])
        tests.append(
            {
                "id": nodeid,
                "s": _status(entry.get("o", "")),
                "o": entry.get("o", "")[-8:],
                "d": round(statistics.median(durations), 4) if durations else None,
            }
        )
        own = nodeid.split("::", 1)[0]
        for path in sorted({own, *mapped.get(nodeid, {})}):
            links.append([len(tests) - 1, files.setdefault(path, len(files))])
    return {
        "project": project,
        "mapped": bool(mapped),
        "files": list(files),
        "tests": tests,
        "links": links,
        "more": max(len(nodeids) - MAX_TESTS, 0),
    }


def html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = resources.files(__package__).joinpath("graph.html").read_text(encoding="utf-8")
    return page.replace("{{project}}", _escape(data["project"])).replace("/*DATA*/null", payload)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write(config: Any, path: str | None) -> tuple[str, dict[str, Any]]:
    from _pytest.cacheprovider import Cache

    cache = Cache.for_config(config, _ispytest=True)
    try:
        stored = cache.get(affected.KEY, {})
    except Exception:
        stored = {}
    data = build(stored, History(cache), config.rootpath.name)
    out = path or str(cache.mkdir("glow-graph") / "graph.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html(data))
    return os.path.abspath(out), data
