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
    group.addoption(
        "--glow-sound",
        action="store_true",
        default=None,
        help="play a sound when the run ends (also PYTEST_GLOW_SOUND=1 or glow_sound = true in the ini)",
    )
    group.addoption(
        "--glow-share",
        nargs="?",
        const="glow-card.svg",
        default=None,
        metavar="PATH",
        help="save the run as an SVG card to share (default: glow-card.svg); implies --glow",
    )
    group.addoption(
        "--glow-wrapped",
        action="store_true",
        default=False,
        help="show everything glow remembers about this project (with --glow-share, save it as SVG) and exit",
    )
    parser.addini("glow_boss", "fight the test suite as a boss", type="bool", default=False)
    parser.addini("glow_sound", "play a sound when the run ends", type="bool", default=False)


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
    if config.getoption("glow_share", None):
        return True
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


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config: pytest.Config) -> int | None:
    if not config.getoption("glow_wrapped", False):
        return None
    from _pytest.cacheprovider import Cache
    from rich.console import Console

    from . import wrapped
    from .history import History

    share = config.getoption("glow_share", None)
    if share and not share.lower().endswith(".svg"):
        raise pytest.UsageError(f"--glow-share writes SVG; give it a .svg path, not {share!r}")
    history = History(Cache.for_config(config, _ispytest=True))
    recap = wrapped.render_wrapped(history, config.rootpath.name)
    console = Console(highlight=False, width=min(Console().width, 100))
    console.print(recap)
    if share:
        wrapped.save(recap, share)
        console.print(f"  ✦ saved {share}", style="dim", soft_wrap=True)
    return 0


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    share = config.getoption("glow_share", None)
    if share and not share.lower().endswith(".svg"):
        raise pytest.UsageError(f"--glow-share writes SVG; give it a .svg path, not {share!r}")
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
