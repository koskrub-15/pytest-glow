import io
import os
import random
import sys

import pytest
from rich.console import Console

from pytest_glow import chat


def _chat():
    return chat.Chat("shop", random.Random(1))


def test_chat_reacts_to_what_happens():
    c = _chat()
    c.started(0.0, 120)
    assert len(c.messages) == 1
    c.passed(1.0, "test_a.py::test_x", combo=25)
    assert c.messages[-1].text in {line.format(n=25) for line in chat.COMBO}
    watching = c.viewers
    c.failed(2.0, "test_a.py::test_vat", "ConnectionError: could not connect to postgres", broke=25)
    texts = [m.text for m in list(c.messages)[-3:]]
    assert texts[0] in {line.format(n=25) for line in chat.BROKE}
    assert texts[1] in chat.NETWORK
    assert c.viewers < watching


def test_chat_notices_a_slow_test_once_and_gets_restless():
    c = _chat()
    c.started(0.0, 3)
    c.tick(4.0, {"test_a.py::test_upload": 0.5})
    assert c.messages[-1].text in {line.format(test="test_upload", secs="3.50s") for line in chat.SLOW_TEST} | set(
        chat.SLOW_TEST
    )
    said = len(c.messages)
    c.tick(4.1, {"test_a.py::test_upload": 0.5})
    assert len(c.messages) == said
    c.tick(4.0 + chat.RESTLESS + 0.1, {})
    assert c.messages[-1].text in chat.RESTLESS_LINES


def test_chat_panel_keeps_its_size():
    c = _chat()
    console = Console(width=chat.WIDTH, file=io.StringIO())
    for n in (0, 3, 20):
        for i in range(n):
            c.failed(float(i), f"test_a.py::test_{'x' * 80}", "AssertionError: " + "y" * 80, broke=None)
        lines = console.render_lines(c.panel(5), console.options)
        assert len(lines) == 7 and all(sum(seg.cell_length for seg in line) == chat.WIDTH for line in lines)
    assert chat.viewers_text(1234) == "1.2k" and chat.viewers_text(999) == "999"


def test_no_chat_without_a_terminal(pytester):
    pytester.makepyfile("def test_a():\n    pass\n\ndef test_b():\n    assert 0\n")
    result = pytester.runpytest("--glow", "--glow-chat", "--glow-roast")
    out = result.stdout.str()
    assert "1 passed" in out and "watching" not in out and "🔥" not in out


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pty")
def test_the_live_view_is_as_wide_as_its_terminal_while_a_test_runs(monkeypatch):
    import fcntl
    import struct
    import termios

    from pytest_glow.reporter import TermConsole

    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.delenv("LINES", raising=False)
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 150, 0, 0))
    with os.fdopen(slave, "w") as terminal:
        # fds 0-2 are pytest's files here, as they are while any test runs: Rich alone would say 80
        assert Console(file=terminal).width == 80
        assert TermConsole(file=terminal).width == 150
    os.close(master)
