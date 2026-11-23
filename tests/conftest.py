import pytest

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def _no_job_summary(monkeypatch):
    # our own CI sets it: the runs inside the tests mustn't write into the real job summary
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


@pytest.fixture(autouse=True)
def _no_quests(monkeypatch):
    # quests depend on the date: they'd make the XP the runs earn change from day to day
    monkeypatch.setenv("PYTEST_GLOW_QUESTS", "0")


@pytest.fixture(autouse=True)
def _no_shiny(monkeypatch):
    # a 1-in-500 shiny run pays 250 XP: it'd fail a test that counts XP, once in a while
    monkeypatch.setenv("PYTEST_GLOW_SHINY_ODDS", "0")
