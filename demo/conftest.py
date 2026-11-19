import time

import pytest


@pytest.fixture(scope="session")
def app():
    time.sleep(0.4)  # booting the app once for the whole run
    yield
    time.sleep(0.15)


@pytest.fixture
def database(app):
    raise ConnectionError("could not connect to postgres://localhost:5432")
