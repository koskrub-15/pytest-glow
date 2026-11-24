import json
import re

import pytest

from pytest_glow import graph
from pytest_glow.history import History

STORED = {
    "tests": {
        "tests/test_a.py::test_x": {"app.py": "1", "tests/test_a.py": "2"},
        "tests/test_a.py::test_y": {"tests/test_a.py": "2"},
    }
}


def history(**outcomes):
    h = History(None)
    h.tests = {f"tests/test_a.py::{name}": {"o": o, "d": [0.1, 0.2, 0.3]} for name, o in outcomes.items()}
    return h


def test_build_from_the_affected_map():
    data = graph.build(STORED, history(test_x="PPF", test_y="PFPFP"), "shop")
    assert data["mapped"] and data["files"] == ["app.py", "tests/test_a.py"]
    assert [(t["id"].split("::")[1], t["s"], t["d"]) for t in data["tests"]] == [
        ("test_x", "failing", 0.2),
        ("test_y", "flaky", 0.2),
    ]
    assert data["links"] == [[0, 0], [0, 1], [1, 1]]  # every test to its own file too


def test_the_files_no_test_runs():
    stored = {
        "tests": {"tests/test_a.py::test_x": {"app/shop.py": "1"}},
        "files": {
            path: [0, size, "h"]
            for path, size in {
                "app/shop.py": 10,
                "app/unused.py": 10,  # no test, not covered: this is the news
                "app/constants.py": 10,  # run on import, covered: nothing for a test to run
                "app/__init__.py": 0,
                "migrations/0001.py": 10,  # not where the code under test is
                "tests/test_a.py": 10,
                "tests/conftest.py": 10,
            }.items()
        },
    }
    h = History(None)
    h.coverage = {"app/shop.py": 90.0, "app/unused.py": 40.0, "app/constants.py": 100.0}
    data = graph.build(stored, h, "shop")
    assert [data["files"][i] for i in data["untested"]] == ["app/unused.py"]
    assert data["cov"] == {"app/shop.py": 90.0, "app/unused.py": 40.0}


def test_build_without_a_map_has_the_tests_by_file():
    data = graph.build({}, history(test_x="P"), "shop")
    assert not data["mapped"] and data["files"] == ["tests/test_a.py"] and data["tests"][0]["s"] == "passed"


def test_the_page_cant_be_broken_out_of():
    stored = {"tests": {"tests/test_a.py::test_x[</script><b>]": {}}}
    page = graph.html(graph.build(stored, History(None), "<shop>"))
    assert "</script><b>" not in page and "&lt;shop&gt; · glow graph" in page
    payload = re.search(r"const DATA = (.*);\n", page).group(1)
    assert json.loads(payload)["tests"][0]["id"] == "tests/test_a.py::test_x[</script><b>]"


def test_glow_graph_draws_and_runs_nothing(pytester):
    pytester.makepyfile(test_g="def test_one(): pass\ndef test_two(): pass\n")
    pytester.runpytest_subprocess("--glow")
    result = pytester.runpytest_subprocess("--glow-graph=out.html")
    assert result.ret == 0
    out = result.stdout.str()
    assert "glow graph" in out and "2 tests · 1 file · " in out and "--glow-affected" in out
    assert "passed" not in out
    page = (pytester.path / "out.html").read_text()
    assert "test_g.py::test_one" in page and "<canvas" in page


def test_glow_graph_wants_html(pytester):
    result = pytester.runpytest_subprocess("--glow-graph=out.svg")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
