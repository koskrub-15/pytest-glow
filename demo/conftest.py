import pytest


@pytest.fixture
def database():
    raise ConnectionError("could not connect to postgres://localhost:5432")
