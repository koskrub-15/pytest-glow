"""pytest entry point: decides whether to glow and swaps the terminal reporter."""

from __future__ import annotations

import os
import sys

import pytest

# Modes that drive the stock reporter's terminal writer directly, or print
# test-by-test output of their own; the live view would only get in their way.
_INCOMPATIBLE = (
    "help",
    "version",
    "collectonly",
    "showfixtures",
    "show_fixtures_per_test",
    "markers",
    "setuponly",
    "setupplan",
    "setupshow",
    "pastebin",
    "debug",
    "traceconfig",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("glow", "pytest-glow")
    group.addoption(
        "--glow",
        action="store_true",
        dest="glow",
        default=None,
        help="use the glow reporter even when stdout is not a terminal",
    )
    group.addoption("--no-glow", action="store_false", dest="glow", help="use pytest's standard reporter")
    group.addoption(
        "--glow-boss",
        action="store_true",
        default=None,
        help="fight the test suite as a boss (also PYTEST_GLOW_BOSS=1 or glow_boss = true in the ini)",
    )
    parser.addini("glow_boss", "fight the test suite as a boss", type="bool", default=False)


_TRUE = ("1", "true", "yes", "on")


def flag(config: pytest.Config, name: str) -> bool:
    """An opt-in mode, from the command line, the environment or the ini file."""
    if config.getoption(f"glow_{name}", None):
        return True
    if os.environ.get(f"PYTEST_GLOW_{name.upper()}", "").strip().lower() in _TRUE:
        return True
    try:
        return bool(config.getini(f"glow_{name}"))
    except ValueError:
        return False


def _wanted(config: pytest.Config) -> bool | None:
    """True/False when the user decided, None to decide automatically."""
    option = config.getoption("glow", None)
    if option is not None:
        return option
    env = os.environ.get("PYTEST_GLOW", "").strip().lower()
    if env in ("0", "false", "no", "off"):
        return False
    if env in _TRUE:
        return True
    return None


def _compatible(config: pytest.Config) -> bool:
    if hasattr(config, "workerinput"):  # an xdist worker: the controller does the reporting
        return False
    if any(getattr(config.option, name, False) for name in _INCOMPATIBLE):
        return False
    if config.option.verbose < -1:
        return False
    try:
        if config.getini("log_cli") or config.getoption("log_cli_level", None):
            return False
    except ValueError:
        pass
    return True


def _terminal_stream(force: bool):
    try:
        fd = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        return None
    if not force and (not os.isatty(fd) or os.environ.get("TERM") == "dumb" or sys.platform == "win32"):
        return None  # Windows consoles: untested, so only with an explicit --glow
    # Our own handle on the terminal: while tests run, fd capture points fd 1 at a
    # temp file, but the live view keeps refreshing in the background.
    return os.fdopen(os.dup(fd), "w", buffering=1, encoding=sys.stdout.encoding or "utf-8", errors="replace")


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    wanted = _wanted(config)
    if wanted is False or not _compatible(config):
        return
    standard = config.pluginmanager.get_plugin("terminalreporter")
    if standard is None:
        return
    stream = _terminal_stream(force=bool(wanted))
    if stream is None:
        return

    from .reporter import GlowReporter

    config.add_cleanup(stream.close)
    reporter = GlowReporter(config, stream, force=bool(wanted))
    config.pluginmanager.unregister(standard)
    config.pluginmanager.register(reporter, "terminalreporter")
