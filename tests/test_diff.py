from collections import namedtuple
from dataclasses import dataclass

import pytest

from pytest_glow.diff import explain


def lines(left, right):
    found = explain(left, right)
    assert found is not None
    return found.render().plain.splitlines(), found.summary


def test_dicts_show_only_what_changed():
    out, summary = lines({"name": "ada", "role": "user", "x": 1}, {"name": "ada", "role": "admin", "y": 2})
    assert out == ["~ 'role': 'user' → 'admin'", "- 'x': 1", "+ 'y': 2", "  … 1 identical key"]
    assert summary == "role: 'user' → 'admin'  (+2 more)"


def test_nested_paths():
    _, summary = lines({"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}})
    assert summary == "a.b.c: 1 → 2"


def test_lists_align_items_and_mention_length_last():
    out, summary = lines([1, 2, 3], [1, 20, 3, 4])
    assert out == ["length 3 → 4", "  … 1 identical item", "~ [1]: 2 → 20", "  … 1 identical item", "+ [3] 4"]
    assert summary == "[1]: 2 → 20  (+2 more)"


def test_lists_of_dicts_are_diffed_inside():
    _, summary = lines([{"id": 1, "v": "a"}], [{"id": 1, "v": "b"}])
    assert summary == "[0].v: 'a' → 'b'"


def test_numbers_show_the_delta():
    out, summary = lines(4.0, 4.5)
    assert out == ["4.0 → 4.5   Δ -0.5  (-11.1%)"]
    assert summary == "4.0 ≠ 4.5"


def test_strings_are_cropped_to_the_difference():
    out, summary = lines("x" * 100 + "abc", "x" * 100 + "abd")
    assert out[0].startswith("- …") and out[0].endswith("abc")
    assert summary == "strings differ at char 102"


def test_multiline_strings_diff_by_line():
    out, summary = lines("a\nb\nc", "a\nB\nc\nd")
    assert out == ["  a", "- b", "+ B", "  c", "+ d"]
    assert summary == "text differs from line 2"


def test_sets():
    out, _ = lines({1, 2}, {2, 3})
    assert out == ["- 1", "+ 3", "  … 1 in both"]


@dataclass
class User:
    name: str
    role: str


Point = namedtuple("Point", "x y")


def test_dataclasses_and_namedtuples_diff_by_field():
    out, _ = lines(User("ada", "admin"), User("ada", "user"))
    assert out == ["~ role: 'admin' → 'user'", "  … 1 identical field"]
    assert lines(Point(1, 2), Point(1, 3))[1] == "y: 2 → 3"


@pytest.mark.parametrize(("left", "right"), [(4, "4"), (True, False), (object(), object()), (None, 1)])
def test_nothing_to_add(left, right):
    assert explain(left, right) is None


def test_a_broken_eq_does_not_break_the_report():
    class Weird:
        def __eq__(self, other):
            raise RuntimeError("no")

        __hash__ = object.__hash__

    assert explain({"a": Weird()}, {"a": 1}) is not None


def test_huge_diffs_are_cut():
    out, _ = lines(list(range(200)), [x + 1 if x % 2 else x for x in range(200)])
    assert len(out) == 41 and out[-1].startswith("… ")
