from pytest_glow import advice
from pytest_glow.reporter import FixtureTime


def test_function_fixtures_set_up_over_and_over():
    fixtures = {
        ("client", "function"): FixtureTime(setup=5.4, count=54),
        ("db", "session"): FixtureTime(setup=5.0, count=1),  # already wide
        ("tmp_path", "function"): FixtureTime(setup=3.0, count=50),  # not the project's
        ("rare", "function"): FixtureTime(setup=3.0, count=2),  # set up too few times
    }
    (tip,) = advice.fixture_scopes(fixtures, {"client", "db", "rare"}, duration=12.0)
    assert tip.what == "client is set up 54× at 100ms each: 5.40s, 45% of the run"
    assert 'scope="module"' in tip.do


def test_libraries_slow_on_purpose():
    (tip,) = advice.slow_libraries({"argon2": 7.3, "bcrypt": 0.1, "requests": 5.0}, duration=11.8)
    assert tip.what == "argon2 takes 7.30s, 62% of the run"
    assert "time_cost=1" in tip.do


def test_sleeps():
    (tip,) = advice.sleeps({"t.py::test_a": 1.5, "t.py::test_b": 0.6, "t.py::test_c": 0.1}, duration=10.0)
    assert tip.what == "tests sleep for 2.20s, 22% of the run (test_a 1.50s, test_b 600ms)"
    assert advice.sleeps({"t.py::test_a": 0.4}, duration=1.0) == []  # not worth half a second


def test_the_biggest_tips_first():
    small, big = advice.Tip(1, "small", ""), advice.Tip(5, "big", "")
    assert [t.what for t in advice.tips([small], [big])] == ["big", "small"]
    assert len(advice.tips([advice.Tip(i, str(i), "") for i in range(10)])) == advice.MAX_TIPS
