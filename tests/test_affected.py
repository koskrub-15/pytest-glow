import re
import sys
from types import SimpleNamespace

import pytest

from pytest_glow import affected

needs_monitoring = pytest.mark.skipif(not affected.supported(), reason="sys.monitoring is Python 3.12+")


def items(*nodeids):
    return [SimpleNamespace(nodeid=n) for n in nodeids]


def files(**hashes):
    return {path.replace("__", "/").replace("_py", ".py"): [0, 0, h] for path, h in hashes.items()}


STORED = {
    "files": files(app_py="a1", tax_py="t1", tests__test_a_py="x1", tests__conftest_py="c1"),
    "tests": {
        "tests/test_a.py::test_app": {"app.py": "a1", "tests/test_a.py": "x1"},
        "tests/test_a.py::test_tax": {"tax.py": "t1", "tests/test_a.py": "x1"},
    },
}
BOTH = ("tests/test_a.py::test_app", "tests/test_a.py::test_tax")


def pick(now, *nodeids, failing=()):
    choice = affected.choose(items(*nodeids), STORED, now, set(failing), lambda item: item.nodeid)
    return [i.nodeid for i in choice.selected], choice


def test_only_the_tests_that_ran_a_changed_file():
    picked, choice = pick(files(app_py="a2", tax_py="t1", tests__test_a_py="x1", tests__conftest_py="c1"), *BOTH)
    assert picked == ["tests/test_a.py::test_app"]
    assert choice.why == {"changed": 1} and choice.changed == ["app.py"]


def test_nothing_changed_nothing_runs():
    picked, choice = pick(STORED["files"], *BOTH)
    assert picked == [] and len(choice.deselected) == 2 and choice.everything is None


def test_new_and_failing_tests_run():
    picked, choice = pick(STORED["files"], *BOTH, "tests/test_a.py::test_new", failing={"tests/test_a.py::test_tax"})
    assert picked == ["tests/test_a.py::test_tax", "tests/test_a.py::test_new"]
    assert choice.why == {"new": 1, "failing": 1}


def test_a_changed_file_no_test_ran_runs_everything():
    now = {**STORED["files"], "settings.py": [0, 0, "s2"]}
    stored = {**STORED, "files": {**STORED["files"], "settings.py": [0, 0, "s1"]}}
    choice = affected.choose(items(*BOTH), stored, now, set(), lambda item: item.nodeid)
    assert len(choice.selected) == 2 and "settings.py" in choice.everything


def test_a_changed_conftest_runs_the_tests_under_it():
    picked, _ = pick(files(app_py="a1", tax_py="t1", tests__test_a_py="x1", tests__conftest_py="c2"), *BOTH)
    assert picked == list(BOTH)


def test_the_first_run_runs_everything():
    choice = affected.choose(items(*BOTH), {}, STORED["files"], set(), lambda item: item.nodeid)
    assert len(choice.selected) == 2 and choice.everything.startswith("first run")


def test_snapshot_reads_only_what_changed_on_disk(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    first = affected.snapshot(str(tmp_path), {})
    stale = {"a.py": [*first["a.py"][:2], "remembered"]}
    assert affected.snapshot(str(tmp_path), stale)["a.py"][2] == "remembered"  # same mtime and size: not read
    (tmp_path / "a.py").write_text("x = 22\n")
    assert affected.snapshot(str(tmp_path), stale)["a.py"][2] not in ("remembered", first["a.py"][2])


# -- end to end ---------------------------------------------------------------------------------------------

PROJECT = {
    "shop": "from tax import vat\ndef total(p):\n    return p + vat(p)\ndef count(p):\n    return len(p)\n",
    "tax": "from settings import RATE\ndef vat(x):\n    return x * RATE\n",
    "settings": "RATE = 0.5\n",
    "db": "def connect():\n    return [1, 2, 3]\n",
    "conftest": "import pytest\nfrom db import connect\n"
    "@pytest.fixture(scope='session')\ndef rows():\n    return connect()\n",
    "test_shop": "from shop import count, total\ndef test_total(): assert total(2) == 3\n"
    "def test_count(): assert count([1]) == 1\n",
    "test_db": "def test_rows(rows): assert rows == [1, 2, 3]\ndef test_more(rows): assert len(rows) == 3\n",
}


def ran(pytester, *args):
    result = pytester.runpytest_subprocess("--no-glow", "--glow-affected", "-rA", "-p", "no:randomly", *args)
    names = sorted(line.split("::")[-1].split()[0] for line in result.outlines if line.startswith("PASSED "))
    return names, result


def edit(pytester, name, line="# edited\n"):
    path = pytester.path / f"{name}.py"
    path.write_text(path.read_text().rstrip("\n") + "\n" + line)


@needs_monitoring
def test_affected_end_to_end(pytester):
    pytester.makepyfile(**PROJECT)
    names, _ = ran(pytester)
    assert names == ["test_count", "test_more", "test_rows", "test_total"]  # learning
    names, result = ran(pytester)
    assert names == [] and result.ret == 0  # nothing changed: a success, not "no tests collected"
    edit(pytester, "tax")
    assert ran(pytester)[0] == ["test_total"]
    edit(pytester, "db")  # set up once, in the first test that needs it: counts for both
    assert ran(pytester)[0] == ["test_more", "test_rows"]
    edit(pytester, "settings")  # constants only: no test runs its code, so it can't tell
    assert ran(pytester)[0] == ["test_count", "test_more", "test_rows", "test_total"]


@needs_monitoring
def test_affected_keeps_running_what_fails(pytester):
    pytester.makepyfile(**PROJECT)
    ran(pytester)
    edit(pytester, "tax", "def vat(x):\n    return 0\n")
    _, result = ran(pytester)
    result.assert_outcomes(failed=1)
    _, result = ran(pytester)  # nothing changed, but it still fails
    result.assert_outcomes(failed=1)


@needs_monitoring
def test_affected_under_xdist(pytester):
    pytest.importorskip("xdist")
    pytester.makepyfile(**PROJECT)
    ran(pytester, "-n", "2")
    edit(pytester, "shop")
    assert ran(pytester, "-n", "2")[0] == ["test_count", "test_total"]
    edit(pytester, "test_db", "")
    _, result = ran(pytester, "-n", "2")
    assert result.ret == 0


@needs_monitoring
def test_affected_in_the_glow_header(pytester):
    pytester.makepyfile(**PROJECT)

    def out():
        return re.sub(
            r"\x1b\[[0-9;?]*[A-Za-z]", "", pytester.runpytest_subprocess("--glow", "--glow-affected").stdout.str()
        )

    out()
    edit(pytester, "tax")
    assert "◎ affected: 1 of 4 tests · 1 changed  (tax.py)" in out()
    text = out()
    assert "none of 4 tests" in text and "NOTHING CHANGED" in text


@pytest.mark.skipif(affected.supported(), reason="only before Python 3.12")
def test_affected_needs_python_312(pytester):
    pytester.makepyfile(test_a="def test_a(): pass\n")
    result = pytester.runpytest_subprocess("--glow", "--glow-affected")
    assert "◎ affected: needs Python 3.12+, so all of them" in re.sub(
        r"\x1b\[[0-9;?]*[A-Za-z]", "", result.stdout.str()
    )
    assert result.ret == 0


def test_affected_leaves_coverage_tools_alone():
    if affected.supported():
        tracker = affected.Tracker(".")
        assert tracker.start()
        assert sys.monitoring.get_tool(tracker.tool) == "pytest-glow"
        tracker.stop()
        assert sys.monitoring.get_tool(affected.TOOL_IDS[0]) is None


@needs_monitoring
def test_affected_doesnt_count_the_coverage_of_a_part(pytester):
    pytest.importorskip("pytest_cov")
    pytester.makepyfile(**PROJECT)

    def run(*args):
        result = pytester.runpytest_subprocess("--glow", "--glow-affected", "--cov=.", "--cov-fail-under=95", *args)
        return result.ret, re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", result.stdout.str())

    code, out = run()
    assert "covered" in out  # all of them ran: the coverage is the suite's
    code, out = run()
    assert "coverage: not counted, no test ran" in out and "covered" not in out and code == 0
    edit(pytester, "tax")
    code, out = run()
    assert "coverage: not counted, only 1 of 4 tests ran" in out and code == 0  # not below 95% for it
