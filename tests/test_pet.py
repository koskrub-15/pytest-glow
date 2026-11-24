import pytest

from pytest_glow import pet

DAY = 86400


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_GLOW_DATA", str(tmp_path / "data"))
    return tmp_path / "data"


def test_a_pet_lives_and_dies_by_the_runs(tmp_path):
    root = str(tmp_path / "shop")
    p = pet.adopt(root, "Bob", now=0)
    assert pet.line(p, 0).plain == "🥚 Bob · an egg · hatches on the first green run"
    assert pet.live(p, False, 1) == [] and p["red_since"] is not None  # an egg doesn't get sick
    assert pet.live(p, True, 2) == ["hatched"]
    assert [pet.live(p, True, 3) for _ in range(4)][-1] == ["grew"] and pet.stage(p["meals"]) == "kid"
    assert pet.live(p, False, 9.6) == ["sick"]
    assert "♥♥♥♥♥ · dies in 7 days" in pet.line(p, 9.6).plain  # red_since rounds up to 10
    assert pet.live(p, False, 10 + 3 * DAY) == []
    assert "dies in 4 days without a green run" in pet.line(p, 10 + 3 * DAY).plain
    assert pet.live(p, True, 10 + 4 * DAY) == ["recovered", "ate"]
    pet.live(p, False, 20 * DAY)
    assert pet.live(p, True, 27 * DAY) == ["died"]  # too late: a week of red
    assert pet.live(p, True, 28 * DAY) == []
    assert "💀 died today" in pet.line(p, 27 * DAY, ["died"]).plain
    pet.save(root, p)
    again = pet.adopt(root, "Bob II", now=30 * DAY)
    assert [g["name"] for g in again["graves"]] == ["Bob"] and again["meals"] == 0


def test_there_is_only_one_and_it_lives_outside_the_cache(tmp_path, home):
    root = str(tmp_path / "shop")
    pet.adopt(root, "Bob")
    with pytest.raises(ValueError, match="already lives here"):
        pet.adopt(root, "Alice")
    assert pet.path_for(root).startswith(str(home))
    assert pet.load(root)["name"] == "Bob"


def test_glow_adopt(pytester, home):
    pytester.makepyfile("def test_a():\n    pass\n")
    result = pytester.runpytest_subprocess("--glow-adopt")  # no terminal to ask in
    assert result.ret == 4 and "pytest --glow-adopt NAME" in result.stdout.str()
    result = pytester.runpytest_subprocess("--glow-adopt", "Bob")
    assert result.ret == 0 and "signed. Bob is yours now." in result.stdout.str()
    assert "no --glow-abandon" in result.stdout.str()
    result = pytester.runpytest_subprocess("--glow-adopt", "Alice")
    assert "Bob already lives here" in result.stdout.str()


def test_the_pet_stays_out_of_ci(pytester):
    pytester.makepyfile("def test_a():\n    pass\n")
    pet.adopt(str(pytester.path), "Bob")
    result = pytester.runpytest("--glow")
    assert "Bob" not in result.stdout.str()
    assert pet.load(str(pytester.path))["meals"] == 0  # not fed by a run nobody watched
