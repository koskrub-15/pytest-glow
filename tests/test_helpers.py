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
        )
    life = h.life
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
