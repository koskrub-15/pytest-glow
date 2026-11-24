import os
from collections import Counter

import pytest

from pytest_glow import coverage, render
from pytest_glow.history import History, is_flaky


@pytest.mark.parametrize(
    ("lines", "expected"),
    [([], ""), ([7], "7"), ([1, 2, 3], "1-3"), ([1, 2, 5, 7, 8, 9], "1-2, 5, 7-9")],
)
def test_ranges(lines, expected):
    assert coverage.ranges(lines) == expected


@pytest.mark.parametrize(
    ("percent", "precision", "expected"),
    [(66.666, 0, "67%"), (99.6, 0, "99%"), (100.0, 0, "100%"), (0.2, 0, "1%"), (0.0, 0, "0%"), (98.857, 2, "98.86%")],
)
def test_fmt_percent_never_lies_about_100_or_0(percent, precision, expected):
    assert coverage.fmt_percent(percent, precision) == expected


@pytest.mark.parametrize(
    ("outcomes", "flaky"),
    [("", False), ("PPPP", False), ("PPF", False), ("FFPP", False), ("PFP", True), ("PSFSP", True), ("FPFP", True)],
)
def test_is_flaky(outcomes, flaky):
    assert is_flaky(outcomes) is flaky


def test_strip_buckets_keep_the_worst_outcome():
    strip = render.strip(["passed"] * 9 + ["failed"], total=10, width=5)
    assert strip.plain == "━" * 5
    assert [span.style for span in strip.spans][-1] == render.HEX["failed"]


def test_strip_pads_unfinished_tests():
    strip = render.strip(["passed"], total=4, width=10)
    assert len(strip.plain) == 10
    assert [span.style for span in strip.spans] == [render.HEX["passed"]] + [render._TRACK] * 3


def test_proportion_bar_fills_the_width_and_keeps_rare_outcomes_visible():
    bar = render.proportion_bar(Counter(passed=998, failed=1, skipped=1), width=50)
    assert len(bar.plain) == 50
    assert {span.style for span in bar.spans} == {render.HEX[c] for c in ("passed", "failed", "skipped")}


def test_strip_flashes_fresh_tests():
    strip = render.strip(["passed", "passed"], total=2, width=2, ages=[10.0, 0.0])
    assert [span.style for span in strip.spans] == [render.HEX["passed"], "bold #ffffff"]


def test_glow_bar_fills_proportionally():
    bar = render.glow_bar(1, 2, 10, render.GRADIENTS["green"])
    assert len(bar.plain) == 10
    assert bar.spans[-1].style == render._TRACK
    assert sum(1 for span in bar.spans if span.style != render._TRACK) == 5


def test_counts_are_not_dimmed_by_the_separator():
    text = render.counts_text(Counter(passed=2, failed=1), compact=False)
    assert text.style == ""


@pytest.mark.parametrize(
    ("seconds", "expected"), [(0.0001, "<1ms"), (0.25, "250ms"), (3.14159, "3.14s"), (125, "2m05s")]
)
def test_fmt_dur(seconds, expected):
    assert render.fmt_dur(seconds) == expected


def test_crash_message_strips_pytest_colours():
    class Crash:
        message = "\x1b[31massert\x1b[0m 1 == 2\nmore"

    class Report:
        longrepr = type("Repr", (), {"reprcrash": Crash()})()

    assert render.crash_message(Report()) == "assert 1 == 2"


class FakeCache(dict):
    def get(self, key, default):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value


def test_history_round_trip():
    cache = FakeCache()
    history = History(cache)
    history.record(
        {"t::a": ("passed", 0.5), "t::b": ("failed", 1.0)}, 2.0, ok=False, failed=1, coverage=(80.0, {"m.py": 80.0})
    )
    history.save()

    again = History(cache)
    assert again.last_outcome("t::a") == "P"
    assert again.last_outcome("t::b") == "F"
    assert again.last_coverage() == 80.0
    assert again.coverage == {"m.py": 80.0}
    assert again.green_streak() == 0
    assert again.last_comparable_run(2)["d"] == 2.0


def test_history_survives_a_corrupt_cache():
    cache = FakeCache({"glow/history": "garbage"})
    assert History(cache).runs == []
    assert not History(None).enabled


def facts(**kw):
    from pytest_glow.achievements import RunFacts

    base = {"ok": True, "hour": 14, "counts": Counter(passed=3), "done": 3}
    return RunFacts(**{**base, **kw})


@pytest.mark.parametrize(
    ("kw", "key"),
    [
        ({"ok": False, "prior_runs": [{"ok": True}] * 3}, "first_blood"),
        ({"prior_runs": [{"ok": True}] + [{"ok": False}] * 5}, "phoenix"),
        ({"hour": 2}, "night_owl"),
        ({"coverage_files": [(3, 100.0)]}, "minimalist"),
        ({"coverage_total": 89.96, "fail_under": 90.0, "precision": 0}, "sniper"),
        ({"new_pb": True}, "speedrunner"),
        ({"longest_fixed_streak": 5}, "surgeon"),
        ({"done": 120, "counts": Counter(passed=120)}, "clean_sweep"),
        ({"green_streak": 100}, "centurion"),
        ({"weekday": 4, "hour": 18}, "friday_deploy"),
        ({"ok": False, "oldest_blame": 6 * 365 * 86400}, "archaeologist"),
        ({"ok": False, "coverage_total": 100.0}, "glass_cannon"),
        ({"max_combo": 100}, "unstoppable"),
        ({"boss_slain": True}, "boss_slayer"),
        ({"shiny": True}, "shiny_hunter"),
    ],
)
def test_achievements(kw, key):
    from pytest_glow.achievements import earned

    assert key in {a.key for a in earned(facts(**kw))}


def test_an_ordinary_afternoon_earns_nothing():
    from pytest_glow.achievements import earned

    run = facts(prior_runs=[{"ok": True}] * 5, coverage_files=[(0, 100.0), (40, 100.0)], green_streak=6)
    assert earned(run) == []


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(5, "just now"), (60, "1 minute ago"), (3 * 86400 + 5, "3 days ago"), (400 * 86400, "1 year ago")],
)
def test_ago(seconds, expected):
    from pytest_glow.blame import ago

    assert ago(seconds) == expected


def test_spark_scales_between_min_and_max():
    assert render.spark([1, 2, 3], render.GRADIENTS["cyan"]).plain == "▁▅█"
    assert render.spark([2, 2], render.GRADIENTS["cyan"]).plain == "▅▅"


def test_confetti_frames_keep_their_size():
    confetti = render.Confetti(30, height=4, seed=1)
    for t in (0.0, 0.3, 0.9):
        assert [len(line) for line in confetti.frame(t).plain.split("\n")] == [30] * 4
    assert confetti.frame(0.3).plain.strip()


def test_personal_best_only_counts_green_runs_of_the_same_size():
    history = History(None)
    history.record({"a": ("passed", 0.1)}, 2.0, ok=True, failed=0)
    history.record({"a": ("failed", 0.1)}, 1.0, ok=False, failed=1)
    history.record({"a": ("passed", 0.1), "b": ("passed", 0.1)}, 0.5, ok=True, failed=0)
    assert history.personal_best(1) == 2.0
    assert history.personal_best(2) == 0.5
    assert history.greens == 1


def test_a_broken_combo_glitches_the_screen():
    import random

    text = render.gradient_text("models/test_models.py ━━━━━━━━━━ 41/41", render.GRADIENTS["green"])
    torn = render.glitch(text, 0.5, random.Random(3))
    body = torn.plain.lstrip(" ")
    assert len(body) == len(text.plain) and body != text.plain
    assert set(body) - set(text.plain) <= set(render.GLITCH_CHARS)
    assert render.glitch(text, 0.0, random.Random(3)).plain.strip() == text.plain
    assert "COMBO BREAKER" in render.skill_issue(42, 0.0).plain
    assert "S K I L L   I S S U E" in render.skill_issue(42, render.GLITCH * 0.75).plain


def test_combos_heat_up():
    assert render.combo_stops(10) == render.GRADIENTS["cyan"]
    assert render.combo_stops(150) == render.GRADIENTS["fire"]


def test_every_project_meets_the_same_boss():
    from pytest_glow.boss import BOSSES, Fight

    first = Fight.for_project("my-app")
    assert first.name in BOSSES
    assert Fight.for_project("my-app").name == first.name
    assert len({Fight.for_project(f"p{i}").name for i in range(50)}) > 1


def test_boss_eyes_weaken():
    from pytest_glow.boss import Fight

    fight = Fight.for_project("x", hp=10)
    assert [fight.eyes(left) for left in (10, 4, 1)] == ["●", "◆", "✖"]
    sprite = fight.sprite_text(1, heat=0).plain
    assert "✖" in sprite
    assert len(set(map(len, sprite.split("\n")))) == 1  # rows line up


def test_hearts():
    from pytest_glow.boss import hearts

    assert hearts(0).plain == "❤❤❤"
    assert hearts(2).plain == "❤♡♡"
    assert hearts(9).plain == "♡♡♡"


def test_sound_falls_back_to_the_bell(monkeypatch, tmp_path):
    import io

    from pytest_glow import sound

    monkeypatch.setattr(sound, "_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(sound, "_spawn", lambda path: False)
    out = io.StringIO()
    player = sound.Player.__new__(sound.Player)
    player.stream = out
    player.play("hit")  # mid-run: silence rather than a bell per test
    assert out.getvalue() == ""
    player.play("level_clear", bell=True)
    assert out.getvalue() == "\a"


def test_sound_uses_a_player_when_there_is_one(monkeypatch):
    from pytest_glow import sound

    monkeypatch.setattr(sound.sys, "platform", "linux")
    monkeypatch.setattr(sound.shutil, "which", lambda name: "/usr/bin/aplay" if name == "aplay" else None)
    assert sound.command("x.wav") == ["aplay", "-q", "x.wav"]
    monkeypatch.setattr(sound.shutil, "which", lambda name: "/usr/bin/" + name)
    assert sound.command("x.wav") == ["pw-play", "x.wav"]
    monkeypatch.setattr(sound.shutil, "which", lambda name: None)
    assert sound.command("x.wav") is None


@pytest.mark.parametrize("name", ["level_clear", "sad_trombone", "airhorn", "hit", "boss_down", "combo6"])
def test_sounds_are_valid_wavs_without_clipping(monkeypatch, tmp_path, name):
    import wave

    from pytest_glow import sound

    monkeypatch.setattr(sound, "_cache_dir", lambda: str(tmp_path))
    samples = sound.SOUNDS[name]()
    assert 0.05 < len(samples) / sound.RATE < 3
    assert max(map(abs, samples)) < 1
    assert abs(samples[0]) < 0.01  # no click
    with wave.open(sound.path_for(name)) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (sound.RATE, 2, 1)
        assert w.getnframes() == len(samples)


def test_combo_milestones():
    from pytest_glow import sound

    assert [sound.milestone(n) for n in (9, 10, 11, 25, 100)] == [None, 0, None, 1, 3]
    assert f"combo{len(sound.COMBO_MILESTONES) - 1}" in sound.SOUNDS


def test_hits_are_throttled(monkeypatch):
    from pytest_glow import sound

    played = []
    player = sound.Player.__new__(sound.Player)
    player._last_hit = 0.0
    monkeypatch.setattr(player, "play", played.append, raising=False)
    for _ in range(50):
        player.hit(crit=False)
    player.hit(crit=True)
    assert played == ["hit"]


def test_link_template(monkeypatch):
    from pytest_glow.reporter import link_template

    monkeypatch.delenv("PYTEST_GLOW_LINK", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert link_template() == "file://{path}"
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    assert link_template() == "vscode://file{path}:{line}"
    monkeypatch.setenv("PYTEST_GLOW_LINK", "pycharm://open?file={path}&line={line}")
    assert link_template() == "pycharm://open?file={path}&line={line}"
    monkeypatch.setenv("PYTEST_GLOW_LINK", "off")
    assert link_template() is None


def _blocked_thread(tmp_path):
    """A thread parked inside a function from a file under tmp_path, which calls into the stdlib."""
    import importlib.util
    import threading

    (tmp_path / "slow_mod.py").write_text(
        "import queue\n\ndef fetch(q, ready):\n    ready.set()\n    return q.get()  # parked here\n"
    )
    spec = importlib.util.spec_from_file_location("slow_mod", tmp_path / "slow_mod.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import queue

    q, ready = queue.Queue(), threading.Event()
    thread = threading.Thread(target=module.fetch, args=(q, ready), daemon=True)
    thread.start()
    ready.wait()
    return thread, q


def test_where_a_hanging_test_is(tmp_path):
    import time

    from pytest_glow import hang

    thread, q = _blocked_thread(tmp_path)
    try:
        time.sleep(0.05)
        mine, deeper = hang.stuck_at(hang.thread_frame(thread.ident), str(tmp_path))
        assert (mine.path, mine.line, mine.function) == (str(tmp_path / "slow_mod.py"), 5, "fetch")
        assert mine.source == "return q.get()  # parked here"
        assert deeper is not None and deeper.path.endswith("threading.py")  # queue.get waits on a lock
        text = hang.describe((mine, deeper), str(tmp_path)).plain
        assert text.startswith("⏳ slow_mod.py:5 fetch  return q.get()")
        assert "→ threading.py:" in text
    finally:
        q.put(None)
        thread.join()


def test_short_paths():
    import os

    from pytest_glow.hang import short_path

    here = os.sep + os.path.join("home", "me", "app")
    assert short_path(os.path.join(here, "tests", "t.py"), here) == os.path.join("tests", "t.py")
    site = os.path.join(os.sep, "venv", "lib", "site-packages", "requests", "api.py")
    assert short_path(site, here) == "requests/api.py"
    assert short_path(os.path.join(os.sep, "usr", "lib", "python3", "socket.py"), here) == "socket.py"


def test_levels():
    from pytest_glow import progress

    assert progress.level_of(0) == (1, 0, 100)
    assert progress.level_of(99) == (1, 99, 100)
    assert progress.level_of(100) == (2, 0, 150)
    assert progress.level_of(100 + 150 + 10) == (3, 10, 200)
    assert progress.title(1) == "Print Debugger"
    assert progress.title(4) == "Assert Apprentice"
    assert progress.title(99) == "The One Who Runs pytest"


def test_xp_for_a_run():
    from pytest_glow import progress

    assert progress.xp_for(passed=10, ok=True, max_combo=0, fixed=0, boss_won=False, shiny=False) == 35
    assert progress.xp_for(passed=10, ok=False, max_combo=0, fixed=0, boss_won=False, shiny=False) == 10
    huge = progress.xp_for(passed=50_000, ok=True, max_combo=42, fixed=2, boss_won=True, shiny=True)
    assert huge == progress.MAX_PASS_XP + 25 + 8 + 20 + 100 + 250


def test_xp_line():
    from pytest_glow import progress

    assert progress.xp_line(0, 35).plain == "✦ +35 XP  Lv 1 Print Debugger ▰▰▰▰▱▱▱▱▱▱ 35/100"
    up = progress.xp_line(90, 400).plain
    assert up.startswith("⬆ LEVEL UP  Lv 4 · Assert Apprentice  new title!")
    assert up.endswith("+400 XP")
    assert "new title" not in progress.xp_line(90, 20).plain


def test_prestige_past_the_last_level():
    from pytest_glow import progress

    cycle = progress._cycle()
    assert progress.level_of(cycle - 1)[0] == progress.PRESTIGE_AT
    assert progress.rank(cycle) == (1, 1) and progress.level_of(cycle + 150) == (2, 50, 150)
    line = progress.xp_line(cycle - 10, 35).plain
    assert line.startswith("★ PRESTIGE") and "back to Lv 1, with a star ★" in line
    assert progress.xp_line(cycle, 35).plain == "✦ +35 XP  ★ Lv 1 Print Debugger ▰▰▰▰▱▱▱▱▱▱ 35/100"
    assert progress.stars_text(cycle * 5).plain == "★×5"


def test_lifetime_tally():
    from pytest_glow.history import History

    h = History(None)
    for hour, ok in ((23, True), (23, False), (9, True)):
        h.greens = h.greens + 1 if ok else 0
        h.tally(
            ok=ok,
            counts={"passed": 3, "failed": 0 if ok else 1},
            duration=1.5,
            hour=hour,
            xp=30,
            max_combo=12,
            fixed=0,
            shiny=False,
            boss="won" if ok else "lost",
            loot="🥄 Spoon" if ok else None,
            quests=1,
        )
    life = h.life
    assert life["quests"] == 3
    assert (life["runs"], life["greens"], life["tests"], life["failed"], life["xp"]) == (3, 2, 10, 1, 90)
    assert life["hours"][23] == 2 and life["hours"][9] == 1
    assert (life["boss_won"], life["boss_lost"]) == (2, 1)
    assert life["loot"] == ["🥄 Spoon"]
    assert life["best_combo"] == 12 and life["best_streak"] == 1
    assert h.xp == 90


def test_boss_phases_in_the_arena():
    from rich.console import Console

    from pytest_glow.boss import Fight, arena

    def shown(left):
        console = Console(width=100, record=True, file=open(os.devnull, "w"))  # noqa: SIM115
        console.print(arena(Fight.for_project("x", hp=100), left, 0, 0.0, None, 0))
        return console.export_text()

    assert "ENRAGED" not in shown(60) and "LAST STAND" not in shown(60)
    assert "🔥 ENRAGED" in shown(50)
    assert "💫 LAST STAND" in shown(10)


def test_loot():
    import random

    from pytest_glow.boss import LOOT, RARITY, drop, loot_line

    rng = random.Random(1)
    drops = [drop(rng) for _ in range(2000)]
    assert set(drops) <= set(LOOT)
    share = {r: sum(1 for _, rarity in drops if rarity == r) / len(drops) for r in RARITY}
    assert share["common"] > share["rare"] > share["epic"] > share["legendary"] > 0

    item = ("🗡 Mutex of Destiny", "rare")
    assert loot_line(item, None).plain == "🎁 loot  🗡 Mutex of Destiny  rare"
    assert loot_line(item, ["🥄 Spoon of Mocking"]).plain.endswith("rare · new! · 2/16 collected")
    assert loot_line(item, ["🗡 Mutex of Destiny"]).plain.endswith("rare · 1/16 collected")


def test_wrapped_quips():
    from pytest_glow.wrapped import quip

    assert quip(1.0, 0.5).startswith("Go to sleep")
    assert quip(0.97, 0.0) == "Your CI fears you."
    assert quip(0.1, 0.0) == "Your tests are more of a suggestion."


def test_watch_scan_and_changes(tmp_path):
    from pytest_glow import watch

    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "notes.txt").write_text("not watched\n")
    for skipped in (".venv", "__pycache__", "node_modules", "pkg.egg-info"):
        (tmp_path / skipped).mkdir()
        (tmp_path / skipped / "mod.py").write_text("")
    before = watch.scan(str(tmp_path))
    assert sorted(os.path.basename(p) for p in before) == ["app.py", "pytest.ini"]

    os.utime(tmp_path / "app.py", ns=(1, 1))
    (tmp_path / "new.py").write_text("")
    after = watch.scan(str(tmp_path))
    assert [os.path.basename(p) for p in watch.changes(before, after)] == ["app.py", "new.py"]


def test_watch_runs_the_same_command(monkeypatch):
    import sys

    from pytest_glow import watch

    assert watch.child_args(("-x", "--glow-watch", "tests")) == [
        sys.executable,
        "-m",
        "pytest",
        "-x",
        "tests",
        "--glow-ff",
    ]
    assert watch.child_args(["x"], failed=True, pattern="cart")[-4:] == ["--glow-ff", "--lf", "-k", "cart"]
    assert watch.child_args(["x"], debug=True)[-4:] == ["--glow-ff", "--lf", "--pdb", "-x"]
    assert watch.child_args(["x"], affected=True)[-2:] == ["--glow-ff", "--glow-affected"]
    assert "--glow-affected" not in watch.child_args(["--glow-affected", "x"])  # the watch decides, run by run


def test_watch_keys_from_a_pipe():
    import os

    from pytest_glow import watch

    read, write = os.pipe()
    os.write(write, b"f\n\nquit\nmy pattern\n")
    with open(read, "rb", buffering=0) as stream:
        keys = watch.Keys(stream)
        assert not keys.tty
        assert [keys.key(1), keys.key(1), keys.key(1)] == ["f", "\n", "q"]
        assert keys.line("?") == "my pattern"
        assert keys.key(0.01) is None
        os.close(write)
        assert keys.key(1) == "q"  # closed: nobody left to type


def test_quests_are_the_same_all_day():
    from pytest_glow import quests

    a = quests.pick("2026-11-21", "shop", typical=200, hour=9, has_best=True)
    assert a == quests.pick("2026-11-21", "shop", typical=200, hour=9, has_best=True)
    assert len(a) == 3 and len({key for key, _ in a}) == 3
    days = {
        tuple(k for k, _ in quests.pick(f"2026-11-{d:02d}", "shop", typical=200, hour=9, has_best=True))
        for d in range(1, 29)
    }
    assert len(days) > 5
    late = [quests.pick(f"2026-11-{d:02d}", "x", typical=5, hour=23, has_best=False) for d in range(1, 29)]
    assert not {key for day in late for key, _ in day} & {"early", "speed", "combo"}  # nothing out of reach


def test_quests_progress_and_pay():
    from pytest_glow import quests

    state = {"day": "d", "q": [["greens", 3], ["combo", 50], ["comeback", 1]], "p": {}, "done": []}

    def facts(**kw):
        base = dict(ok=True, ran=10, fixed=0, max_combo=30, hour=12, new_pb=False, comeback=False, spotless=True)
        return quests.RunFacts(**{**base, **kw})

    assert quests.advance(state, facts()) == []
    assert "3 green runs 1/3" in quests.lines(state, [])[0].plain
    done = quests.advance(state, facts(max_combo=60, comeback=True))
    assert [q.key for q, _ in done] == ["combo", "comeback"]
    assert quests.xp(done, state) == 90
    assert state["p"]["combo"] == 60  # the best run, not a sum
    done = quests.advance(state, facts())
    assert quests.swept(state) and quests.xp(done, state) == 40 + quests.SWEEP_XP
    shown = [line.plain for line in quests.lines(state, done)]
    assert "quest complete  3 green runs  +40 XP" in shown[0] and "all dailies done" in shown[1]
    assert quests.advance(state, facts(max_combo=99)) == []  # done is done


def test_quests_start_over_each_day():
    from pytest_glow import quests

    old = {"day": "1999-01-01", "q": [["greens", 3]], "p": {"greens": 2}, "done": []}
    fresh = quests.today(old, "x", typical=50, hour=12, has_best=False)
    assert fresh["day"] != "1999-01-01" and fresh["p"] == {} and len(fresh["q"]) == 3
    assert quests.today(fresh, "x", typical=50, hour=12, has_best=False) is fresh


def test_green_streak_outlives_the_runs_kept():
    from pytest_glow.history import MAX_RUNS, History

    h = History(None)
    for _ in range(MAX_RUNS + 15):
        h.record({"a": ("passed", 0.1)}, 1.0, ok=True, failed=0)
    assert len(h.runs) == MAX_RUNS
    assert h.green_streak() == MAX_RUNS + 15
    h.record({"a": ("failed", 0.1)}, 1.0, ok=False, failed=1)
    h.record({"a": ("passed", 0.1)}, 1.0, ok=True, failed=0)
    assert h.green_streak() == 1


def test_profile_classifies_frames(tmp_path):
    import json
    import os

    from pytest_glow import profile

    sampler = profile.Sampler(str(tmp_path), ["test_*.py"])

    def code_at(path):
        return compile("x = 1", path, "exec")

    assert sampler.classify(code_at(str(tmp_path / "test_cart.py"))) == ("test", "")
    assert sampler.classify(code_at(str(tmp_path / "conftest.py"))) == ("test", "")
    assert sampler.classify(code_at(str(tmp_path / "shop" / "cart.py"))) == ("code", "")
    venv = tmp_path / ".venv" / "lib" / "site-packages" / "requests" / "api.py"
    assert sampler.classify(code_at(str(venv))) == ("lib", "requests")
    assert sampler.classify(json.dumps.__code__) == ("lib", "json")
    assert sampler.classify(code_at("<frozen importlib._bootstrap>")) == ("lib", "imports")
    assert sampler.classify(code_at(os.path.join("x", "_pytest", "runner.py"))) is None
    assert profile.split(2.0, {"test": 1, "code": 3, "lib": 0}) == {"test": 0.5, "code": 1.5, "lib": 0.0}


def test_ghost_bar_puts_the_ghost_where_the_best_run_was():
    from rich.console import Console

    console = Console(width=22, color_system=None)
    with console.capture() as cap:
        console.print(render.GhostBar(5, 10))
    assert cap.get().rstrip("\n") == "╌" * 10 + "👻" + " " * 10
    with console.capture() as cap:
        console.print(render.GhostBar(30, 10))  # the best run is done: the ghost waits at the end
    assert cap.get().rstrip() == "╌" * 20 + "👻"


def test_ghost_race():
    from types import SimpleNamespace

    from pytest_glow.reporter import GlowReporter

    def race(done, since, best=10.0, total=100):
        run = SimpleNamespace(_ghost=best, _t_start=0.0, _done=done, _total=total)
        row = GlowReporter._ghost_row(run, since, total)
        return row[-1].plain if row else None

    assert race(done=60, since=5.0) == "▲ 1.0s ahead"  # the best got to 60 at 6s
    assert race(done=40, since=5.0) == "▼ 1.0s behind"
    assert race(done=1, since=0.5) is None  # too early to tell
    assert race(done=60, since=5.0, best=None) is None


def test_profile_breakdown_breaks_between_shares():
    from types import SimpleNamespace

    from pytest_glow.reporter import GlowReporter, TestState

    ts = TestState(duration=0.7, fixtures=0.2, profile={"test": 15, "code": 55, "lib": 2, "libs": {"contextlib": 2}})
    breakdown = GlowReporter._breakdown(SimpleNamespace(), ts, 57).plain
    assert breakdown == "↳ test 15% · your code 55% · libs 2% (contextlib) ·\n  fixtures 29%"
    assert "\n" not in GlowReporter._breakdown(SimpleNamespace(), ts, 80).plain


def test_wrapped_roles_of_the_week():
    import time

    from pytest_glow.wrapped import roles

    def at(day, hour, **run):  # day 0 is Monday 2026-11-16
        return {"t": time.mktime((2026, 11, 16 + day, hour, 0, 0, 0, 0, -1)), "d": 1.0, "n": 10, "ok": True, **run}

    now = at(6, 23)["t"]
    assert roles([], now) == []
    assert roles([at(-14, 12)], now) == []  # nothing this week
    assert [r[1] for r in roles([at(1, 12)], now)] == ["Zen Master"]

    owl = [at(2, 2), at(3, 3), at(4, 1, ok=False), at(4, 9)]
    found = roles(owl, now)
    assert found[0] == ("🦉", "Night Owl", "3 runs after midnight")

    medic = [at(1, 12 + i % 2, ok=bool(i % 2)) for i in range(6)]
    assert ("🩹", "Medic", "brought it back to green 3×") in roles(medic, now)

    farmer = [at(0, 12, n=10), at(2, 12, n=30)]
    assert ("🌱", "Test Farmer", "+20 tests since the week began") in roles(farmer, now)

    faster = [at(-5, 12, d=10.0)] * 3 + [at(1, 12, d=5.0)] * 3
    assert ("🐇", "Speed Demon", "green runs 50% faster than the week before") in roles(faster, now)

    goblin = [at(2, 10) for _ in range(30)]
    found = roles(goblin, now)
    assert found[0] == ("🔁", "Rerun Goblin", "30 runs on Wednesday alone")
    assert ("🧱", "Unbreakable", "30 runs, not one red") in found
    assert len(roles(owl + goblin + medic, now)) == 3


def test_failure_shape_leaves_out_the_values():
    from pytest_glow.reporter import shape

    assert shape("KeyError: 'u1'") == shape("KeyError: 'u2'") == "KeyError: …"
    assert shape("assert 3 == 4") == "assert … == …"
    assert shape("x1 is not v2.3") == "x1 is not v2.3"  # names keep their digits
    assert shape("bad at 0x7f00aabbcc") == "bad at 0x…"
