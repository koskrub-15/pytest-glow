import math
import time

import pytest


@pytest.mark.parametrize("n", range(24))
def test_square_roots(n):
    time.sleep(0.03)
    assert math.isqrt(n * n) == n


def test_factorial():
    time.sleep(0.2)
    assert math.factorial(5) == 120


def test_average():
    values = [3, 4, 5]
    expected = 4.5
    assert sum(values) / len(values) == expected
