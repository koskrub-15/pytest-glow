import re

import pytest

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

SUITE = """
import pytest

def test_ok():
    assert 1 + 1 == 2

def test_broken():
    values = [1, 2]
    assert values == [1, 3]

@pytest.mark.skip(reason="later")
def test_skipped():
    pass

@pytest.mark.xfail
def test_known_bug():
    assert False
"""


def run(pytester, *args):
    result = pytester.runpytest_subprocess(*args)
    text = ANSI.sub("", "\n".join(result.outlines))
    return result, text


def test_reports_a_green_run(pytester):
    pytester.makepyfile("def test_one(): pass\ndef test_two(): pass\n")
    result, out = run(pytester, "--glow")
    assert result.ret == 0
    assert "ALL GREEN" in out
    assert "2 passed" in out
    assert "test_reports_a_green_run.py" in out


def test_reports_failures_with_rich_tracebacks(pytester):
    pytester.makepyfile(SUITE)
    result, out = run(pytester, "--glow")
    assert result.ret == 1
    assert "FAILED" in out
    assert "1 passed · 1 failed · 1 skipped · 1 xfailed" in out
    assert "failures (1)" in out
    assert "Traceback" in out and "values = [1, 2]" in out
    assert "@py_assert" not in out


def test_falls_back_without_a_terminal(pytester):
    pytester.makepyfile("def test_one(): pass\n")
    result, out = run(pytester)
    assert result.ret == 0
    assert "ALL GREEN" not in out
    result.stdout.fnmatch_lines(["*1 passed*"])


@pytest.mark.parametrize("args", [("--glow", "--no-glow"), ("--glow", "--collect-only")])
def test_stands_aside(pytester, args):
    pytester.makepyfile("def test_one(): pass\n")
    result, out = run(pytester, *args)
    assert "ALL GREEN" not in out
    assert result.ret == 0


def test_env_var_disables(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_GLOW", "0")
    pytester.makepyfile("def test_one(): pass\n")
    _, out = run(pytester)
    assert "✦ glow" not in out


def test_collection_errors(pytester):
    pytester.makepyfile(test_bad="import nonexistent_module_xyz\n", test_good="def test_one(): pass\n")
    result, out = run(pytester, "--glow")
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert "collection error" in out
    assert "nonexistent_module_xyz" in out


def test_setup_errors_are_errors(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.fixture
        def db():
            raise ConnectionError("no db")

        def test_query(db):
            pass
    """)
    result, out = run(pytester, "--glow")
    assert result.ret == 1
    assert "1 error" in out
    assert "error in setup" in out
    assert "ConnectionError: no db" in out


def test_captured_output_of_failures(pytester):
    pytester.makepyfile("def test_loud():\n    print('hello from the test')\n    assert 0\n")
    _, out = run(pytester, "--glow")
    assert "captured stdout call" in out
    assert "hello from the test" in out


def test_history_across_runs(pytester):
    pytester.makepyfile("def test_one(): pass\n")
    _, first = run(pytester, "--glow")
    assert "history starts now" in first
    _, second = run(pytester, "--glow")
    assert "2 green runs in a row" in second

    pytester.makepyfile("def test_one(): assert 0\n")
    _, third = run(pytester, "--glow")
    assert "newly failing" in third

    pytester.makepyfile("def test_one(): pass\n")
    _, fourth = run(pytester, "--glow")
    assert "fixed" in fourth and "back to green" in fourth


def test_flaky_tests_are_spotted(pytester):
    for body in ("pass", "assert 0", "pass", "assert 0"):
        pytester.makepyfile(f"def test_coin(): {body}\n")
        _, out = run(pytester, "--glow")
    assert "flaky" in out


def test_warnings_are_summarised(pytester):
    pytester.makepyfile("""
        import warnings

        def test_old_api():
            warnings.warn("old api", DeprecationWarning)
    """)
    result, out = run(pytester, "--glow", "-W", "default")
    assert result.ret == 0
    assert "warnings (1)" in out
    assert "DeprecationWarning: old api" in out


def test_verbose_lists_every_test(pytester):
    pytester.makepyfile("def test_alpha(): pass\ndef test_beta(): pass\n")
    _, out = run(pytester, "--glow", "-v")
    assert "test_verbose_lists_every_test.py::test_alpha" in out
    assert "test_verbose_lists_every_test.py::test_beta" in out


def test_xdist(pytester):
    pytest.importorskip("xdist")
    pytester.makepyfile(SUITE)
    result, out = run(pytester, "--glow", "-n", "2")
    assert result.ret == 1
    assert "2 workers" in out
    assert "1 passed · 1 failed · 1 skipped · 1 xfailed" in out
    assert "[gw" not in out


def test_other_plugins_terminal_summary_still_runs(pytester):
    pytester.makeconftest("""
        def pytest_terminal_summary(terminalreporter):
            terminalreporter.write_line("coverage: 100%")
    """)
    pytester.makepyfile("def test_one(): pass\n")
    _, out = run(pytester, "--glow")
    assert "coverage: 100%" in out


def test_maxfail_stops_and_says_so(pytester):
    pytester.makepyfile("def test_a(): assert 0\ndef test_b(): assert 0\ndef test_c(): pass\n")
    result, out = run(pytester, "--glow", "-x")
    assert result.ret == 1
    assert "stopping after 1 failures" in out
    assert "1/3" in out


COVERED = """
def used(x):
    if x > 0:
        return "positive"
    return "other"


def unused():
    return 42
"""


def test_coverage_is_drawn_and_tracked(pytester):
    pytest.importorskip("pytest_cov")
    pytester.makepyfile(mathy=COVERED, test_mathy="from mathy import used\ndef test_used(): assert used(1)\n")
    result, out = run(pytester, "--glow", "--cov=mathy", "--cov-report=term-missing")
    assert result.ret == 0
    assert "coverage" in out and "mathy.py" in out
    assert "2 missing  4, 8" in out
    assert "67%" in out and "66%" not in out
    assert "covered" in out
    assert "Stmts" not in out  # pytest-cov's own table is gone

    pytester.makepyfile(test_mathy="from mathy import used, unused\ndef test_used(): assert used(1) and unused()\n")
    _, out = run(pytester, "--glow", "--cov=mathy", "--cov-report=term-missing")
    assert "vs last run" in out and "▲" in out


def test_coverage_fail_under_fails_the_run(pytester):
    pytest.importorskip("pytest_cov")
    pytester.makepyfile(mathy=COVERED, test_mathy="from mathy import used\ndef test_used(): assert used(1)\n")
    result, out = run(pytester, "--glow", "--cov=mathy", "--cov-fail-under=95")
    assert result.ret == 1
    assert "below the required 95%" in out
    assert "FAILED" in out
    assert "Coverage failure: total of" not in out


@pytest.mark.parametrize(
    ("style", "present", "absent"),
    [
        ("no", [], ["failures (1)", "Traceback"]),
        ("short", ["failures (1)", "assert values == [1, 3]"], ["Traceback (most recent call last)"]),
        ("long", ["failures (1)", "Traceback (most recent call last)"], []),
    ],
)
def test_respects_tb_style(pytester, style, present, absent):
    pytester.makepyfile(SUITE)
    result, out = run(pytester, "--glow", f"--tb={style}")
    assert result.ret == 1
    assert "1 failed" in out
    for text in present:
        assert text in out
    for text in absent:
        assert text not in out


def test_summary_waits_for_other_plugins_sessionfinish(pytester):
    # Plugins may finish their numbers in sessionfinish and print them in terminal_summary.
    pytester.makeconftest("""
        state = {}

        def pytest_sessionfinish(session):
            state["done"] = "numbers ready"

        def pytest_terminal_summary(terminalreporter):
            terminalreporter.write_line(state.get("done", "numbers missing"))
    """)
    pytester.makepyfile("def test_one(): pass\n")
    _, out = run(pytester, "--glow")
    assert "numbers ready" in out


def test_traceback_paths_are_relative(pytester):
    pytester.makepyfile("def test_bad():\n    assert 1 == 2\n")
    _, out = run(pytester, "--glow")
    assert "test_traceback_paths_are_relative.py:2 in test_bad" in out
    assert str(pytester.path) not in out


@pytest.mark.parametrize(("n", "egg"), [(69, "nice."), (67, "six seven"), (68, None)])
def test_easter_eggs(pytester, n, egg):
    pytester.makepyfile(f"import pytest\n\n@pytest.mark.parametrize('i', range({n}))\ndef test_n(i): pass\n")
    _, out = run(pytester, "--glow")
    assert f"{n} passed" in out
    for text in ("nice.", "six seven"):
        assert (text in out) == (text == egg)


def test_personal_best(pytester, monkeypatch):
    pytester.makepyfile("import os, time\n\ndef test_one(): time.sleep(float(os.environ.get('NAP', 0)))\n")
    monkeypatch.setenv("NAP", "0.5")
    _, first = run(pytester, "--glow")
    assert "new PB" not in first
    monkeypatch.setenv("NAP", "0")
    _, second = run(pytester, "--glow")
    assert "new PB" in second
    assert "Speedrunner" in second


def test_first_blood_is_unlocked_once(pytester):
    pytester.makepyfile("def test_one(): pass\n")
    run(pytester, "--glow")
    pytester.makepyfile("def test_one(): assert 0\n")
    _, out = run(pytester, "--glow")
    assert "achievement unlocked" in out and "First Blood" in out
    pytester.makepyfile("def test_one(): pass\n")
    run(pytester, "--glow")
    pytester.makepyfile("def test_one(): assert 0\n")
    _, again = run(pytester, "--glow")
    assert "First Blood" not in again


def test_failures_are_blamed(pytester):
    import subprocess

    def git(*args):
        subprocess.run(["git", *args], cwd=pytester.path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "Ada")
    git("config", "user.email", "ada@example.com")
    pytester.makepyfile(test_blamed="def test_bad():\n    assert 1 == 2\n")
    git("add", "test_blamed.py")
    git("commit", "-q", "-m", "a test")
    pytester.makepyfile(test_fresh="def test_new():\n    assert 0\n")
    _, out = run(pytester, "--glow")
    assert "line 2 last touched by you, just now" in out
    assert "not committed yet" in out


def test_no_blame_outside_git(pytester):
    pytester.makepyfile("def test_bad():\n    assert 1 == 2\n")
    _, out = run(pytester, "--glow")
    assert "last touched" not in out and "not committed" not in out


def test_assertion_diffs(pytester):
    pytester.makepyfile("""
        import pytest

        def test_payload():
            assert {"name": "ada", "role": "user"} == {"name": "ada", "role": "admin"}

        def test_caught_compare_is_not_reused():
            with pytest.raises(AssertionError):
                assert 1 == 2
            assert not "a non-comparison"
    """)
    _, out = run(pytester, "--glow")
    assert "test_payload  role: 'user' → 'admin'" in out
    assert "~ 'role': 'user' → 'admin'" in out
    assert "Omitting 1 identical items" not in out
    assert "1 ≠ 2" not in out


def test_short_tracebacks_keep_pytest_text(pytester):
    pytester.makepyfile(test_t="def test_payload():\n    assert {'role': 'user'} == {'role': 'admin'}\n")
    _, out = run(pytester, "--glow", "--tb=short")
    assert "Differing items" in out
    assert "test_payload  role: 'user' → 'admin'" in out
    assert "+ right" not in out


def test_assertion_temporaries_stay_hidden_without_a_diff(pytester):
    pytester.makepyfile(test_t="def test_t():\n    data = {'a': 1}\n    assert not data.get('a')\n")
    _, out = run(pytester, "--glow")
    assert "data = {'a': 1}" in out
    assert "@py_assert" not in out


def test_rerun_hint(pytester):
    pytester.makepyfile(test_r="import pytest\n\n@pytest.mark.parametrize('x', ['a b'])\ndef test_bad(x): assert 0\n")
    _, out = run(pytester, "--glow")
    assert "↻ rerun  pytest 'test_r.py::test_bad[a b]'" in out


def test_rerun_hint_uses_lf_for_many_failures(pytester):
    pytester.makepyfile("import pytest\n\n@pytest.mark.parametrize('i', range(5))\ndef test_bad(i): assert 0\n")
    _, out = run(pytester, "--glow")
    assert "↻ rerun  pytest --lf" in out


def test_slower_than_usual(pytester, monkeypatch):
    pytester.makepyfile(test_s="import os, time\n\ndef test_nap(): time.sleep(float(os.environ['NAP']))\n")
    monkeypatch.setenv("NAP", "0.01")
    for _ in range(3):
        run(pytester, "--glow")
    monkeypatch.setenv("NAP", "0.3")
    _, out = run(pytester, "--glow")
    assert "🐢 slower  test_s.py::test_nap" in out and "usually" in out


def _git_repo(pytester):
    import subprocess

    def git(*args):
        subprocess.run(["git", *args], cwd=pytester.path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "Ada")
    git("config", "user.email", "ada@example.com")
    return git


def test_changes_since_the_last_green_run(pytester):
    import os
    import time

    git = _git_repo(pytester)
    pytester.makepyfile(
        lib="def double(x): return x * 2\n", test_lib="from lib import double\ndef test_d(): assert double(2) == 4\n"
    )
    pytester.makefile(".txt", notes="untouched\n")
    git("add", ".")
    git("commit", "-q", "-m", "green")
    run(pytester, "--glow")
    later = time.time() + 5  # mtimes are coarse on some filesystems
    pytester.makepyfile(lib="def double(x): return x * 3\n")
    os.utime(pytester.path / "lib.py", (later, later))
    _, out = run(pytester, "--glow")
    assert "changed since the last green run" in out
    assert "\n     lib.py\n" in out
    assert "notes.txt" not in out


def test_nothing_changed_hints_at_flakiness(pytester, monkeypatch):
    git = _git_repo(pytester)
    pytester.makepyfile(test_f="import os\ndef test_f(): assert not os.environ.get('BREAK')\n")
    git("add", ".")
    git("commit", "-q", "-m", "green")
    run(pytester, "--glow")
    monkeypatch.setenv("BREAK", "1")
    _, out = run(pytester, "--glow")
    assert "nothing changed in git since the last green run" in out


def test_changed_files_the_failure_points_at_come_first(pytester):
    import os
    import time

    git = _git_repo(pytester)
    pytester.makepyfile(aaa="X = 1\n", test_z="def test_z():\n    assert True\n")
    git("add", ".")
    git("commit", "-q", "-m", "green")
    run(pytester, "--glow")
    pytester.makepyfile(test_z="def test_z():\n    assert False\n")
    pytester.makepyfile(aaa="X = 2\n")
    later = time.time() + 5
    os.utime(pytester.path / "test_z.py", (later, later))
    os.utime(pytester.path / "aaa.py", (later + 5, later + 5))  # newer, but not where it fails
    _, out = run(pytester, "--glow")
    assert out.index("test_z.py  ← failing here") < out.index("     aaa.py")


def test_max_combo_in_the_verdict(pytester):
    pytester.makepyfile(
        test_c="import pytest\n\n@pytest.mark.parametrize('i', range(40))\ndef test_c(i): assert i != 30\n"
    )
    _, out = run(pytester, "--glow")
    assert "max combo ×30" in out


def test_xdist_tracks_what_each_worker_runs(pytester):
    pytest.importorskip("xdist")
    pytester.makeconftest("""
        def pytest_terminal_summary(terminalreporter):
            done = getattr(terminalreporter, "_worker_done", {})
            terminalreporter.write_line(f"workers={len(done)} finished={sum(done.values())}")
    """)
    pytester.makepyfile("import pytest\n@pytest.mark.parametrize('i', range(8))\ndef test_n(i): pass\n")
    _, out = run(pytester, "--glow", "-n", "2")
    assert "workers=2 finished=8" in out


def test_boss_fight_victory(pytester):
    pytester.makepyfile("def test_a(): pass\ndef test_b(): pass\n")
    _, out = run(pytester, "--glow", "--glow-boss")
    assert "VICTORY" in out
    assert "falls · 2 hits in" in out


def test_boss_fight_wounds_and_defeat(pytester):
    pytester.makepyfile("def test_a(): pass\ndef test_b(): assert 0\n")
    _, out = run(pytester, "--glow", "--glow-boss")
    assert "survives with 1 HP" in out
    assert "you have ❤❤♡ left" in out
    pytester.makepyfile("import pytest\n@pytest.mark.parametrize('i', range(4))\ndef test_b(i): assert 0\n")
    _, out = run(pytester, "--glow", "--glow-boss")
    assert "DEFEATED by the" in out


def test_boss_from_the_environment_and_ini(pytester, monkeypatch):
    pytester.makepyfile("def test_a(): pass\n")
    _, out = run(pytester, "--glow")
    assert "VICTORY" not in out
    monkeypatch.setenv("PYTEST_GLOW_BOSS", "1")
    _, out = run(pytester, "--glow")
    assert "VICTORY" in out
    monkeypatch.delenv("PYTEST_GLOW_BOSS")
    pytester.makeini("[pytest]\nglow_boss = true\n")
    _, out = run(pytester, "--glow")
    assert "VICTORY" in out


def test_share_saves_a_card(pytester):
    pytester.makepyfile("def test_a(): pass\ndef test_b(): assert 0\n")
    # no --glow: --glow-share asks for the glow reporter on its own
    _, out = run(pytester, "--glow-share")
    assert "card saved to glow-card.svg" in out
    svg = (pytester.path / "glow-card.svg").read_text()
    assert svg.startswith("<svg")
    assert "passed" in svg and "failed" in svg
    assert pytester.path.name[:20] in svg

    _, out = run(pytester, "--glow-share=out/card.svg")
    assert "couldn't save the card" in out


def test_share_wants_svg(pytester):
    pytester.makepyfile("def test_a(): pass\n")
    result = pytester.runpytest_subprocess("--glow-share=card.png")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "give it a .svg path" in "\n".join(result.errlines)


def test_sound_stays_quiet_without_a_terminal(pytester):
    pytester.makepyfile("def test_a(): pass\n")
    result = pytester.runpytest_subprocess("--glow", "--glow-sound")
    assert "\a" not in "\n".join(result.outlines)


def test_same_failures_are_grouped(pytester):
    pytester.makepyfile(
        test_db="""
        import pytest

        class Box:
            pass

        @pytest.fixture
        def db():
            raise ConnectionError(f"no database, see {Box()!r}")

        @pytest.mark.parametrize("i", range(4))
        def test_query(db, i):
            pass

        def test_math():
            assert 1 == 2
        """
    )
    _, out = run(pytester, "--glow")
    assert "failures (5 · 2 distinct)" in out
    assert "⧉ the same failure in 3 more tests" in out
    assert "test_db.py::test_query[3]" in out
    assert "test_query[0] (setup)  +3 more like this  ConnectionError" in out
    assert out.count("Traceback") == 2


def test_no_links_when_piped(pytester):
    pytester.makepyfile("def test_a(): assert 0\n")
    result = pytester.runpytest_subprocess("--glow")
    assert "\x1b]8;" not in "\n".join(result.outlines)


def test_link_urls(pytester):
    pytester.makeconftest("""
        def pytest_terminal_summary(terminalreporter):
            tr = terminalreporter
            tr._link = "x://{path}:{line}"
            tr.write_line("url=" + tr._url("sub dir/a.py", 3))
            tr.write_line("test=" + tr._test_url("test_links.py::test_a"))
            tr.write_line("crash=" + tr._crash_url(tr.stats["failed"][0]))
    """)
    pytester.makepyfile(test_links="import os\n\ndef test_a():\n    assert os\n    assert 0\n")
    _, out = run(pytester, "--glow")
    root = str(pytester.path).replace(" ", "%20")
    assert f"url=x://{root}/sub%20dir/a.py:3" in out
    assert f"test=x://{root}/test_links.py:3" in out
    assert f"crash=x://{root}/test_links.py:5" in out


def test_slowest_fixtures(pytester):
    pytester.makepyfile(
        test_fx="""
        import time
        import pytest

        @pytest.fixture(scope="session")
        def db():
            time.sleep(0.3)
            yield
            time.sleep(0.15)

        @pytest.fixture
        def client(db):
            time.sleep(0.03)

        @pytest.mark.parametrize("i", range(4))
        def test_a(client, i):
            pass
        """
    )
    _, out = run(pytester, "--glow")
    assert "slowest fixtures" in out
    # times only from below: a busy CI runner is slower, never faster
    db = next(line for line in out.splitlines() if " db " in line)
    assert "session · " in db
    assert _seconds(re.search(r"setup (\S+),", db)[1]) >= 0.3
    assert _seconds(re.search(r"teardown (\S+?)[ ·…]", db + " ")[1]) >= 0.15
    client = next(line for line in out.splitlines() if " client " in line)
    assert _seconds(re.search(r"×4, (\S+) each", client)[1]) >= 0.03
    assert out.index(" db ") < out.index(" client ")


def _seconds(shown):
    return float(shown[:-2]) / 1000 if shown.endswith("ms") else float(shown[:-1])


def test_no_fixture_section_for_quick_fixtures(pytester):
    pytester.makepyfile("import pytest\n@pytest.fixture\ndef f(): pass\ndef test_a(f): pass\n")
    _, out = run(pytester, "--glow")
    assert "slowest fixtures" not in out


def test_xp_and_level_up(pytester):
    pytester.makepyfile("import pytest\n@pytest.mark.parametrize('i', range(80))\ndef test_a(i): pass\n")
    _, out = run(pytester, "--glow")
    assert "⬆ LEVEL UP  Lv 2 · Print Debugger  +121 XP" in out  # 80 passed, green, combo ×80
    pytester.makepyfile("def test_a(): pass\n")
    _, out = run(pytester, "--glow")
    assert "✦ +26 XP  Lv 2 Print Debugger" in out
    assert "47/150" in out


SHINY = "import pytest_glow.reporter\npytest_glow.reporter.SHINY_ODDS = 1.0\n"


def test_shiny_run(pytester):
    pytester.makeconftest(SHINY)
    pytester.makepyfile("def test_a(): pass\n")
    _, out = run(pytester, "--glow")
    assert "✦ SHINY ✦" in out
    assert "a 1-in-500 run" in out
    assert "Shiny Hunter" in out
    assert "+276 XP" in out  # 1 passed + 25 for green + 250 for shiny


def test_red_runs_are_never_shiny(pytester):
    pytester.makeconftest(SHINY)
    pytester.makepyfile("def test_a(): assert 0\n")
    _, out = run(pytester, "--glow")
    assert "SHINY" not in out
    assert "FAILED" in out


def test_a_slain_boss_drops_loot(pytester):
    pytester.makepyfile("def test_a(): pass\n")
    _, out = run(pytester, "--glow", "--glow-boss")
    assert "🎁 loot  " in out
    assert "new! · 1/16 collected" in out
    _, out = run(pytester, "--glow", "--glow-boss")
    assert re.search(r"· [12]/16 collected", out)


def test_no_loot_when_the_boss_survives(pytester):
    pytester.makepyfile("def test_a(): assert 0\n")
    _, out = run(pytester, "--glow", "--glow-boss")
    assert "🎁" not in out


def test_wrapped(pytester):
    _, out = run(pytester, "--glow-wrapped")
    assert "no history here yet" in out

    pytester.makepyfile(
        "import pytest\n"
        "@pytest.mark.parametrize('i', range(12))\n"
        "def test_a(i): pass\n"
        "def test_slow():\n"
        "    import time; time.sleep(0.12)\n"
    )
    for _ in range(3):
        run(pytester, "--glow", "--glow-boss")
    result, out = run(pytester, "--glow-wrapped", "--glow-share", "recap.svg")
    assert result.ret == 0
    assert "YOUR PYTEST WRAPPED" in out
    assert "3 runs" in out and "39 tests" in out and "100% green" in out
    assert "Lv 3 Assert Apprentice" in out and "420 XP" in out  # 3 × (13 passed + 25 green + 2 combo + 100 boss)
    assert re.search(r"longest green streak +3 runs", out)
    assert re.search(r"best combo +×13", out)
    assert "test_wrapped.py::test_slow" in out
    assert "👹 3 won · 0 lost" in out
    assert "collected" not in out  # nothing ran: no verdict
    assert (pytester.path / "recap.svg").read_text().startswith("<svg")


def test_github_job_summary(pytester, monkeypatch):
    summary = pytester.path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/app")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(pytester.path))
    pytester.makepyfile(
        "import pytest\n"
        "@pytest.fixture\n"
        "def db():\n"
        "    raise ConnectionError('no db')\n"
        "def test_ok(): pass\n"
        "def test_payload(): assert {'role': 'user', 'id': 1} == {'role': 'admin', 'id': 1}\n"
        "def test_a(db): pass\n"
        "def test_b(db): pass\n"
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, failed=1, errors=2)
    assert "✦" not in result.stdout.str()  # the log itself stays plain pytest
    text = summary.read_text()
    assert text.startswith("### ❌ pytest: 1 failed · 2 errors · 1 passed\n")
    assert "| ❌ | `test_github_job_summary.py::test_payload` |" in text
    assert "[test_github_job_summary.py:6](https://github.com/me/app/blob/abc123/test_github_job_summary.py#L6)" in text
    assert "role: 'user' → 'admin'" in text
    assert "(setup) <sub>+1 more like this</sub>" in text
    assert "ConnectionError: no db" in text

    pytester.makepyfile("def test_ok(): pass\n")
    pytester.runpytest_subprocess("-p", "no:cacheprovider")
    assert summary.read_text().count("### ") == 2  # appended, for several pytest steps in one job
    assert "### ✅ pytest: all green · 1 passed" in summary.read_text()


def test_no_job_summary_when_turned_off(pytester, monkeypatch):
    summary = pytester.path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("PYTEST_GLOW_SUMMARY", "0")
    pytester.makepyfile("def test_ok(): pass\n")
    pytester.runpytest_subprocess()
    assert not summary.exists()


def test_glow_ff_runs_the_likely_failures_first(pytester, monkeypatch):
    pytester.makepyfile(
        test_a="def test_one(): pass\ndef test_two(): pass\n",
        test_b="def test_broken(): assert 0\n",
        test_cart="def test_total(): pass\n",
    )
    run(pytester, "--glow")
    pytester.makepyfile(test_c="def test_new(): pass\n")
    monkeypatch.setenv("PYTEST_GLOW_CHANGED", "cart.py")  # as if shop/cart.py had been edited
    _, out = run(pytester, "--glow", "--glow-ff", "-v")
    assert "↯ first: 1 failing · 1 changed · 1 new" in out
    ran = re.findall(r"(test_\w+\.py::test_\w+)", out[out.index("↯") :])
    assert ran[:5] == [
        "test_b.py::test_broken",
        "test_b.py::test_broken",  # once as it fails, once in the -v list
        "test_cart.py::test_total",
        "test_c.py::test_new",
        "test_a.py::test_one",
    ]


def test_glow_ff_off_keeps_the_order(pytester):
    pytester.makepyfile(test_a="def test_one(): pass\n", test_b="def test_broken(): assert 0\n")
    run(pytester, "--glow")
    _, out = run(pytester, "--glow", "-v")
    assert "↯" not in out
    assert out.index("test_a.py::test_one") < out.index("test_b.py::test_broken")


FLAKY_TEST = """
import pathlib

def test_flaky():
    marker = pathlib.Path("tried")
    if not marker.exists():
        marker.write_text("x")
        assert 0, "network blip"

def test_broken():
    assert 0, "always"
"""


def test_glow_rerun_calls_out_flaky_tests(pytester):
    pytester.makepyfile(test_f=FLAKY_TEST)
    result, out = run(pytester, "--glow", "--glow-rerun", "-k", "test_flaky")
    assert result.ret == 0
    assert "〰 GREEN, BUT FLAKY" in out
    assert "1 passed · 1 flaky" in out
    assert "test_f.py::test_flaky  flaky, passed on try 2 · network blip" in out


def test_glow_rerun_gives_up(pytester):
    pytester.makepyfile(test_f=FLAKY_TEST)
    result, out = run(pytester, "--glow", "--glow-rerun=2", "-k", "test_broken")
    assert result.ret == 1
    assert "1 failed" in out and "flaky" not in out


def test_glow_rerun_with_the_standard_reporter(pytester, monkeypatch):
    pytester.makepyfile(test_f=FLAKY_TEST)
    monkeypatch.setenv("PYTEST_GLOW_RERUN", "1")
    result = pytester.runpytest_subprocess("--no-glow", "-rA", "-n", "2", "-p", "xdist")
    result.assert_outcomes(passed=1, failed=1)


def test_flaky_tests_in_the_job_summary(pytester, monkeypatch):
    summary = pytester.path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    pytester.makepyfile(test_f=FLAKY_TEST)
    pytester.runpytest_subprocess("--glow-rerun", "-k", "test_flaky")
    text = summary.read_text()
    assert text.startswith("### 〰️ pytest: green, but flaky · 1 passed · 1 flaky")
    assert "| 〰️ | `test_f.py::test_flaky` | 2 | AssertionError: network blip |" in text


def test_glow_rerun_rejects_nonsense(pytester):
    pytester.makepyfile("def test_ok(): pass\n")
    result = pytester.runpytest_subprocess("--glow-rerun=lots")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "takes a number of reruns" in result.stderr.str()


def test_glow_watch(pytester):
    import queue
    import subprocess
    import sys
    import threading

    pytester.makepyfile(calc="def add(a, b):\n    return a - b\n")
    pytester.makepyfile(test_calc="from calc import add\n\ndef test_add():\n    assert add(2, 2) == 4\n")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "--glow-watch", "-p", "no:randomly"],
        cwd=pytester.path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()

    def until(word):
        seen = []
        while True:
            line = lines.get(timeout=30)
            seen.append(ANSI.sub("", line))
            if word in line:
                return "".join(seen)

    try:
        first = until("watching")
        assert "glow watch · run 1" in first and "1 failed" in first
        (pytester.path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        second = until("watching")
        assert "run 2 · changed calc.py" in second
        assert "1 passed" in second
        proc.stdin.write("\n")
        proc.stdin.flush()
        assert "run 3" in until("watching")
        (pytester.path / "calc.py").write_text("def add(a, b):\n    return a * b - 4\n")
        assert "1 failed" in until("watching")
        proc.stdin.write("f\n")
        proc.stdin.flush()
        only = until("watching")
        assert "run 5 · only failed" in only and "f all tests" in only
        proc.stdin.write("p\nnothing_matches\n")
        proc.stdin.flush()
        assert "-k nothing_matches" in until("watching")
        proc.stdin.write("\n")
        proc.stdin.flush()
        everything = until("watching")
        assert "👀 glow watch · run 7\n" in everything  # no "only failed", no -k
        proc.stdin.write("q\n")
        proc.stdin.flush()
        assert proc.wait(timeout=30) == 1
    finally:
        proc.kill()


def test_a_failure_remembers_when_and_where_it_last_passed(pytester, monkeypatch):
    git = _git_repo(pytester)
    pytester.makepyfile(test_m="import os\ndef test_m(): assert not os.environ.get('BREAK')\n")
    git("add", ".")
    git("commit", "-q", "-m", "green")
    run(pytester, "--glow")
    monkeypatch.setenv("BREAK", "1")
    _, out = run(pytester, "--glow")
    assert "↳ passed just now on this commit" in out
    for n in range(2):
        pytester.makefile(".txt", **{f"n{n}": "x"})
        git("add", ".")
        git("commit", "-q", "-m", f"change {n}")
    _, out = run(pytester, "--glow")
    assert re.search(r"↳ red for 2 runs, same failure · passed just now at [0-9a-f]{7}, 2 commits back", out)


def test_a_failure_that_never_passed(pytester):
    pytester.makepyfile(test_n="def test_n(): assert False\n")
    _, out = run(pytester, "--glow")
    assert "↳ red for" not in out and "never seen" not in out  # nothing remembered yet
    _, out = run(pytester, "--glow")
    assert "↳ red for 2 runs, same failure · never seen it pass" in out


def test_a_failure_knows_if_it_fails_the_same_way(pytester, monkeypatch):
    pytester.makepyfile(test_w="import os\ndef test_w(): assert os.environ.get('V') == 'ok'\n")
    monkeypatch.setenv("V", "a")
    run(pytester, "--glow")
    _, out = run(pytester, "--glow")
    assert "↳ red for 2 runs, same failure" in out
    monkeypatch.setenv("V", "b")
    _, out = run(pytester, "--glow")
    assert "↳ red for 3 runs, a new failure" in out


def test_daily_quests_in_the_verdict(pytester, monkeypatch):
    monkeypatch.delenv("PYTEST_GLOW_QUESTS")
    pytester.makeconftest(
        "import pytest_glow.quests as q\nq.pick = lambda *a, **k: [['greens', 2], ['volume', 100], ['spotless', 1]]\n"
    )
    pytester.makepyfile("def test_a(): pass\n")
    _, out = run(pytester, "--glow")
    assert "quest complete  a green run, no warnings, no skips  +40 XP" in out
    assert "✦ +66 XP" in out  # 1 + 25 for green + 40 for the quest
    _, out = run(pytester, "--glow")
    assert "quest complete  2 green runs" in out
    assert "📜 dailies ✓ 2 green runs · run 100 tests 2/100 · ✓ a green run" in out


def test_quests_can_be_turned_off(pytester):
    pytester.makepyfile("def test_a(): pass\n")
    _, out = run(pytester, "--glow")
    assert "📜" not in out


_BUSY = (
    "import time\n"
    "def busy(seconds):\n"
    "    end = time.perf_counter() + seconds\n"
    "    while time.perf_counter() < end:\n"
    "        pass\n"
)


def _profiled_project(pytester):
    pytester.makepyfile(
        shop=_BUSY,
        test_slow=(
            "import time, pytest\nfrom shop import busy\n"
            "@pytest.fixture\ndef warm():\n    busy(0.2)\n"
            "def test_slow(warm):\n    busy(0.4)\n"
            "    end = time.perf_counter() + 0.1\n    while time.perf_counter() < end:\n        pass\n"
        ),
    )


def test_glow_profile(pytester):
    _profiled_project(pytester)
    _, out = run(pytester, "--glow", "--glow-profile")
    found = re.search(r"↳ test (\d+)% · your code (\d+)% · fixtures (\d+)%", out)
    assert found, out
    test, code, fixtures = map(int, found.groups())
    assert 5 <= test <= 30 and 45 <= code <= 75 and 15 <= fixtures <= 45
    assert re.search(r"where \S+ in tests went", out)
    assert re.search(r"in fixtures: your code \d+ms", out)


def test_glow_profile_under_xdist(pytester):
    pytest.importorskip("xdist")
    _profiled_project(pytester)
    _, out = run(pytester, "--glow", "--glow-profile", "-n", "2")
    assert re.search(r"↳ test \d+% · your code \d+%", out)


def test_no_profile_unless_asked(pytester):
    _profiled_project(pytester)
    _, out = run(pytester, "--glow")
    assert "in tests went" not in out and "↳ test" not in out


def test_pace_compares_with_a_run_of_as_many_tests(pytester):
    pytester.makepyfile(test_p="import pytest\n@pytest.mark.parametrize('i', range(3))\ndef test_p(i): pass\n")
    run(pytester, "--glow")
    _, out = run(pytester, "--glow")
    assert re.search(r"(same pace as|faster than|slower than) last run", out)
    run(pytester, "--glow", "-k", "0")
    _, out = run(pytester, "--glow")
    assert re.search(r"(same pace as|faster than|slower than) the last run of 3 tests", out)
