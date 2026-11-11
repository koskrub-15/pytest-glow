import random
import sys
import time

import pytest


@pytest.mark.skipif(sys.platform == "linux", reason="windows only")
def test_registry():
    pass


@pytest.mark.xfail(reason="known rounding bug")
def test_rounding():
    assert round(2.675, 2) == 2.68


def test_flaky_network():
    time.sleep(0.3)
    assert random.random() > 0.35, "network blip"


def test_report_rendering(capsys):
    print("rendering 3 pages…")
    print("page 2 overflowed")
    time.sleep(0.4)
    assert "overflow" not in "page 2 overflowed"
