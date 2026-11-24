import re
import subprocess

import pytest

from pytest_glow import culprit
from pytest_glow.history import History

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def test_first_bad_is_a_binary_search():
    commits = [f"c{i}" for i in range(16)]
    asked = []

    def verdict(c):
        asked.append(c)
        return culprit.BAD if int(c[1:]) >= 11 else culprit.GOOD

    assert culprit.first_bad(commits, verdict) == ["c11"]
    assert len(asked) <= 4


def test_first_bad_steps_over_what_cant_run():
    said = {"c0": "good", "c1": "skip", "c2": "skip", "c3": "bad", "c4": "bad", "c5": "bad"}
    assert culprit.first_bad(list(said), said.__getitem__) == ["c1", "c2", "c3"]  # c1, c2 can't say: any of them
    said = {"c0": "good", "c1": "good", "c2": "skip", "c3": "good", "c4": "bad"}
    assert culprit.first_bad(list(said), said.__getitem__) == ["c4"]  # around what can't run
    said = {"c0": "good", "c1": "skip", "c2": "bad"}  # c1 or c2: can't tell
    assert culprit.first_bad(list(said), said.__getitem__) == ["c1", "c2"]


def test_resolve_finds_the_test_and_where_it_last_passed():
    h = History(None)
    h.tests = {
        "tests/test_a.py::test_vat": {"p": [1, "abc123"]},
        "tests/test_a.py::test_vat_zero": {"p": [1]},
        "tests/test_b.py::test_rate": {},
    }
    assert culprit.resolve(h, "test_vat") == ("tests/test_a.py::test_vat", "abc123")
    assert culprit.resolve(h, "test_rate@v1.0") == ("tests/test_b.py::test_rate", "v1.0")
    with pytest.raises(culprit.Trouble, match="more than one test"):
        culprit.resolve(h, "vat")
    with pytest.raises(culprit.Trouble, match=re.escape("--glow-bisect 'tests/test_b.py::test_rate@")):
        culprit.resolve(h, "test_rate")


def _repo(pytester):
    def git(*args):
        subprocess.run(["git", *args], cwd=pytester.path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "Ada")
    git("config", "user.email", "ada@example.com")
    pytester.makefile(".gitignore", "__pycache__/\n.pytest_cache/\n")
    pytester.makepyfile(
        tax="def vat(x):\n    return x * 0.2\n",
        test_tax="from tax import vat\n\ndef test_vat():\n    assert vat(10) == 2\n",
    )
    git("add", ".")
    git("commit", "-qm", "vat")
    return git


def bisect(pytester, *args):
    result = pytester.runpytest_subprocess("--glow-bisect", *args)
    return result.ret, ANSI.sub("", result.stdout.str())


def test_glow_bisect_finds_the_commit(pytester):
    git = _repo(pytester)
    pytester.runpytest_subprocess("--glow")  # remembers the commit it passed at
    for i in range(6):
        if i == 3:
            pytester.makepyfile(tax="def vat(x):\n    return round(x * 0.21, 2)\n")
        else:
            pytester.makepyfile(notes=f"N = {i}\n")
        git("add", ".")
        git("commit", "-qm", "new rate" if i == 3 else f"tidy {i}")
    code, out = bisect(pytester, "test_vat")
    assert code == 0
    assert re.search(r"💥 broke in \w+  “new rate”  Ada", out)
    assert "assert 2.1 == 2" in out and "changed tax.py" in out
    assert "glow-bisect-" not in subprocess.check_output(["git", "worktree", "list"], cwd=pytester.path, text=True)


def test_glow_bisect_when_it_isnt_committed(pytester):
    _repo(pytester)
    pytester.runpytest_subprocess("--glow")
    pytester.makepyfile(tax="def vat(x):\n    return 0\n")  # broken, not committed
    code, out = bisect(pytester, "test_vat")
    assert code == 0 and "passes at HEAD: what breaks it isn't committed yet" in out
    assert (pytester.path / "tax.py").read_text().strip() == "def vat(x):\n    return 0"  # left as it was


def test_glow_bisect_without_a_known_good_commit(pytester):
    _repo(pytester)
    code, out = bisect(pytester, "test_vat")
    assert code == 4 and "@<commit or tag>" in out
