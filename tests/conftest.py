import pytest

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def _no_job_summary(monkeypatch):
    # our own CI sets it: the runs inside the tests mustn't write into the real job summary
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
