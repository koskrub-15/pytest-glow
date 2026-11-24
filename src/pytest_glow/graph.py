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
    untested = []
    if mapped:  # the project's files no test runs code from: the map knows them all
        # where the code under test lives (apps/, src/): not migrations, scripts or docs next to it
        roots = {_root(path) for path in files if not _test_file(path)}
        covered = _coverage(history.coverage, {path: 0 for path in stored.get("files", {})})
        for path, entry in sorted(stored.get("files", {}).items()):
            if path in files or _test_file(path) or _root(path) not in roots or entry[1] == 0:
                continue
            if covered.get(path) == 100:  # constants, run on import: nothing in it for a test to run
                continue
            untested.append(files.setdefault(path, len(files)))
    return {
        "project": project,
        "mapped": bool(mapped),
        "files": list(files),
        "untested": untested,
        "cov": _coverage(history.coverage, files),
        "tests": tests,
        "links": links,
        "more": max(len(nodeids) - MAX_TESTS, 0),
    }


def _root(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else ""


def _test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")


def _coverage(measured: dict[str, float], files: dict[str, int]) -> dict[str, float]:
    """The last coverage of each file drawn, as coverage.py named it: relative to where pytest ran, or not."""
    found = {}
    for path, percent in measured.items():
        path = path.replace(os.sep, "/")
        for drawn in files:
            if drawn == path or path.endswith("/" + drawn) or drawn.endswith("/" + path):
                found[drawn] = round(percent, 1)
    return found


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
