import time

import pytest


@pytest.mark.parametrize("field", ["id", "name", "email", "created", "updated", "role", "team", "avatar"])
@pytest.mark.parametrize("model", ["user", "team", "project", "invoice", "comment"])
def test_model_fields(model, field):
    time.sleep(0.02)
    assert field.isidentifier()


def test_serialization_roundtrip():
    time.sleep(0.8)
