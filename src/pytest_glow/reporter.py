"""GlowReporter: pytest's TerminalReporter with a live rich view instead of dots."""

from __future__ import annotations

import contextlib
import os
import platform
import random
import re
import shlex
import threading
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from typing import IO, Any

import pytest
from _pytest.terminal import TerminalReporter
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from . import __version__, hang, progress, render, rerun, share, sound
from . import achievements as ach
from . import coverage as cov
from . import diff as assert_diff
from .blame import ago, blame, changed_since, commits_since, describe, head
from .boss import HEARTS, Fight, arena, drop, loot_line, outcome
from .history import History, is_flaky
from .order import GROUPS
from .plugin import ORDERED, flag

SUMMARY_EXIT_CODES = (
    pytest.ExitCode.OK,
    pytest.ExitCode.TESTS_FAILED,
    pytest.ExitCode.INTERRUPTED,
    pytest.ExitCode.USAGE_ERROR,
    pytest.ExitCode.NO_TESTS_COLLECTED,
)
MAX_ACTIVE_FILES = 6
MAX_RUNNING_TESTS = 5
SLOW_RUNNING = 0.5  # seconds before a running test shows up in the live view
REVEAL = 0.45  # seconds the final verdict takes to sweep in on a terminal
CELEBRATE = 0.95  # seconds of confetti for a personal best or an achievement
MAX_BLAMES = 10
EASTER_EGGS = {69: "nice.", 67: "six seven 🤷"}
MAX_WORKERS_SHOWN = 8
COMBO_SHOWN = 10  # passes in a row before the live view starts counting a combo
COMBO_BROKEN = 1.5  # seconds a broken combo stays on screen
MAX_RERUN_IDS = 3  # beyond this, the rerun hint is `pytest --lf`
SHINY_ODDS = 1 / 500  # the chance that a green run comes out shiny
SLOWER = 2.0  # a test this many times its usual duration (and 100ms more) is called out


@dataclass
class FileState:
    path: str
    total: int
    done: int = 0
    categories: list = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    duration: float = 0.0
    started: float | None = None
    finished_at: list = field(default_factory=list)
    flushed: bool = False
    spinner: Spinner = field(default_factory=lambda: Spinner("dots", style="cyan"))


@dataclass
class TestState:
    outcome: str | None = None
    duration: float = 0.0
    finished: bool = False


@dataclass
class FixtureTime:
    setup: float = 0.0
    teardown: float = 0.0
    count: int = 0

    @property
    def total(self) -> float:
        return self.setup + self.teardown


@dataclass
class Failure:
    report: Any
    traceback: Any = None
    diff: assert_diff.Diff | None = None


_WARNING_LOCATION = re.compile(r"^\S+:\d+: ")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,}")
MAX_GROUPED_IDS = 8


def link_template() -> str | None:
    """How file links open: PYTEST_GLOW_LINK, else at the line in VS Code's terminal, else file://."""
    custom = os.environ.get("PYTEST_GLOW_LINK", "").strip()
    if custom.lower() in ("0", "off", "false", "no"):
        return None
    if custom:
        return custom
    if os.environ.get("TERM_PROGRAM") == "vscode":
        return "vscode://file{path}:{line}"
    return "file://{path}"


def _signature(report: Any) -> tuple | None:
    """Failures with the same signature failed the same way: same place, same message."""
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is None:
        return None
    return (report.when, str(crash.path), crash.lineno, _ADDRESS.sub("0x…", render.crash_message(report)))


def group_failures(failures: list) -> list[list]:
    """Failures grouped by signature, in the order each group first failed."""
    groups: dict[Any, list] = {}
    for i, failure in enumerate(failures):
        groups.setdefault(_signature(failure.report) or i, []).append(failure)
    return list(groups.values())


def _markup_style(markup: dict) -> str:
    return " ".join(k for k, v in markup.items() if v and k not in ("flush", "erase"))


class _LiveView:
    def __init__(self, reporter: GlowReporter) -> None:
        self.reporter = reporter

    def __rich__(self):
        return self.reporter._render_live()


class GlowReporter(TerminalReporter):
    def __init__(self, config: pytest.Config, stream: IO[str], force: bool = False) -> None:
        super().__init__(config, stream)
        color = config.getoption("color", "auto")
        self.console = Console(
            file=stream,
            force_terminal=True if (color == "yes" or force) else None,
            no_color=color == "no",
            highlight=False,
        )
        self._live_enabled = stream.isatty() and self.console.is_terminal
        # clickable paths (OSC 8) only in a real terminal: in logs they'd be noise
        self._link = link_template() if self._live_enabled else None
        self._locations: dict[str, tuple] = {}  # nodeid -> (path from the rootdir, 0-based line)
        self._fixtures: dict[tuple[str, str], FixtureTime] = {}  # (name, scope) -> time spent in it
        self._live: Live | None = None
        self._lock = threading.RLock()
        self._capture_off = config.getoption("capture", "fd") == "no"
        self._verbose = config.option.verbose
        # --tb=auto/long get rich tracebacks; short/line/native keep pytest's own text; no hides them.
        self._tbstyle = config.getoption("tbstyle", "auto")
        self._suppressed: list[str] = []

        self._files: dict[str, FileState] = {}
        self._tests: dict[str, TestState] = {}
        self._running: dict[str, float] = {}
        self._counts: Counter = Counter()
        self._failures: list[Failure] = []
        self._flaky: list[tuple[str, int, str]] = []  # (nodeid, attempts it took, how it failed first)
        self._tracebacks: dict[tuple[str, str], Any] = {}
        self._compare: tuple[Any, Any] | None = None  # operands of the last failed `==` assertion
        self._diffs: dict[tuple[str, str], assert_diff.Diff] = {}
        self._collect_errors: list[Any] = []
        self._workers: set[str] = set()
        self._status = ""
        self._total = 0
        self._done = 0
        self._planned = False
        self._announced = False
        self._t_start = time.monotonic()
        self._t_run: float | None = None
        self._path_width = 20
        self._collect_spinner = Spinner("dots", style="magenta")
        self._history = History(getattr(config, "cache", None))
        self._coverage: cov.CoverageResult | None = None
        started = time.localtime()
        self._hour, self._weekday = started.tm_hour, started.tm_wday
        self._combo = 0
        self._max_combo = 0
        self._combo_broken: tuple[int, float] | None = None  # (combo, when)
        self._oldest_blame: float | None = None
        self._shiny = False
        self._boss_phase = 0
        self._loot: tuple[str, str] | None = None
        self._xp: tuple[int, int] | None = None  # (XP before this run, XP it earned)
        self._fixed = 0
        self._fight = Fight.for_project(config.rootpath.name) if flag(config, "boss") else None
        self._last_hit: float | None = None
        # sound only in an interactive terminal: never in CI or a pipe
        self._player = sound.Player(self.console.file) if flag(config, "sound") and self._live_enabled else None
        self._share: str | None = config.getoption("glow_share", None)
        # under xdist: what each worker is running, and how many tests it has finished
        self._worker_now: dict[str, tuple[str, float]] = {}
        self._worker_done: Counter = Counter()
        self._worker_spinners: dict[str, Spinner] = {}
        self._duration = 0.0
        self._new_pb: float | None = None  # the record this run just beat
        self._unlocked: list[ach.Achievement] = []
        self._blamed_paths: set[str] = set()  # rootdir-relative files the failures point at

    # -- output plumbing ---------------------------------------------------------------
    # Other plugins (xdist, coverage, ...) write through the terminal reporter. While the
    # live view is up, their lines go above it instead of tearing through it.

    def _print(self, *renderables: Any) -> None:
        self.console.print(*renderables, overflow="ellipsis", crop=True, no_wrap=True)

    def write(self, content: str, *, flush: bool = False, **markup: bool) -> None:
        if "Coverage failure: total of" in content and self.config.pluginmanager.has_plugin("_cov"):
            self._suppressed.append(content)  # pytest-cov's verdict; ours goes in the final panel
            return
        if self._live is None:
            return super().write(content, flush=flush, **markup)
        for line in content.splitlines():
            if line.strip():
                self._print(Text(line, style=_markup_style(markup)))

    def write_line(self, line: str | bytes, **markup: bool) -> None:
        if self._live is None:
            return super().write_line(line, **markup)
        line = line.decode(errors="replace") if isinstance(line, bytes) else line
        if line.strip():
            self._print(Text(line, style=_markup_style(markup)))

    def line(self, msg: str, **kw: bool) -> None:
        if self._live is None:
            return super().line(msg, **kw)
        self.write_line(msg, **kw)

    def rewrite(self, line: str, **markup: bool) -> None:
        if self._live is None:
            return super().rewrite(line, **markup)
        self._status = line.strip()

    def write_sep(self, sep: str, title: str | None = None, fullwidth: int | None = None, **markup: bool) -> None:
        if self._live is None:
            return super().write_sep(sep, title, fullwidth, **markup)
        self.console.rule(title or "", style=_markup_style(markup) or "dim")

    def section(self, title: str, sep: str = "=", **kw: bool) -> None:
        if self._live is None:
            return super().section(title, sep, **kw)
        self.write_sep(sep, title, **kw)

    def ensure_newline(self) -> None:
        if self._live is None:
            super().ensure_newline()

    def _start_live(self) -> None:
        if self._live is not None or not self._live_enabled:
            return
        self._live = Live(
            _LiveView(self),
            console=self.console,
            refresh_per_second=12,
            transient=True,
            redirect_stdout=self._capture_off,
            redirect_stderr=self._capture_off,
        )
        self._live.start()

    def _stop_live(self) -> None:
        live, self._live = self._live, None
        if live is not None:
            live.stop()

    # -- session & collection ----------------------------------------------------------

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self._session = session
        self._main_thread = threading.get_ident()  # where the tests run, unless xdist runs them elsewhere
        try:
            from _pytest import timing

            self._session_start = timing.Instant()
        except (ImportError, AttributeError):
            pass
        self._t_start = time.monotonic()
        self._adopt_xdist()
        self._print_header()
        self._start_live()

    def _adopt_xdist(self) -> None:
        # xdist may have grabbed the stock reporter before we replaced it.
        dsession = self.config.pluginmanager.get_plugin("dsession")
        if dsession is not None and hasattr(dsession, "terminal"):
            dsession.terminal = self
        if dsession is not None:
            # xdist relays logstart/logfinish without saying which worker sent them
            for event in ("worker_logstart", "worker_logfinish"):
                relay = getattr(dsession, event, None)
                if callable(relay):
                    setattr(dsession, event, self._tracking(relay, event == "worker_logstart"))
        trdist = self.config.pluginmanager.get_plugin("terminaldistreporter")
        if trdist is not None:
            trdist.tr = self
            trdist._isatty = True

    def _tracking(self, relay, starting: bool):
        def track(node: Any, **kw: Any) -> Any:
            worker = str(getattr(getattr(node, "gateway", None), "id", ""))
            nodeid = kw.get("nodeid", "")
            if worker:
                with self._lock:
                    if starting:
                        self._worker_now[worker] = (nodeid, time.monotonic())
                    else:
                        self._worker_done[worker] += 1
                        if self._worker_now.get(worker, ("",))[0] == nodeid:
                            del self._worker_now[worker]
            return relay(node=node, **kw)

        return track

    def pytest_report_header(self, config: pytest.Config) -> list[str]:
        return []

    def _print_header(self) -> None:
        root = str(self.config.rootpath)
        home = os.path.expanduser("~")
        if root.startswith(home):
            root = "~" + root[len(home) :]
        bits = [f"python {platform.python_version()}", f"pytest {pytest.__version__}", root]
        if self.config.inipath:
            bits.append(self.config.inipath.name)
        header = Text.assemble(
            render.gradient_text(" ✦ glow ", render.GRADIENTS["glow"], background=True), "  ", (" · ".join(bits), "dim")
        )
        self._print(header)
        plugins = sorted(
            {dist.project_name for _, dist in self.config.pluginmanager.list_plugin_distinfo()} - {"pytest-glow"}
        )
        if plugins:
            self._print(Text(f"   plugins: {', '.join(plugins)}", style="dim"))
        lines = self.config.hook.pytest_report_header(config=self.config, start_path=self.startpath)
        for group in reversed(lines):
            for line in [group] if isinstance(group, str) else group:
                self._print(Text(f"   {line}", style="dim"))

    def pytest_collection(self) -> None:
        pass

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self._add_stats("error", [report])
            self._collect_errors.append(report)
            self._print(
                Text.assemble(
                    ("  ✗ ", "bold red"),
                    ("collection error ", "red"),
                    self._node(report.nodeid or "."),
                    ("  " + render.crash_message(report), "dim red"),
                )
            )
        elif report.skipped:
            self._add_stats("skipped", [report])
        self._numcollected += sum(1 for x in report.result if isinstance(x, pytest.Item))

    def report_collect(self, final: bool = False) -> None:
        pass

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self._plan([item.nodeid for item in session.items])
        lines = self.config.hook.pytest_report_collectionfinish(
            config=self.config, start_path=self.startpath, items=session.items
        )
        for group in reversed(lines):
            for line in [group] if isinstance(group, str) else group:
                self._print(Text(f"   {line}", style="dim"))

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        with self._lock:
            self._workers.add(str(getattr(getattr(node, "gateway", None), "id", node)))
        self._plan(ids)

    def _plan(self, nodeids: list[str]) -> None:
        with self._lock:
            if self._planned:
                return
            self._planned = True
            per_file = Counter(render.file_of(n) for n in nodeids)
            for path, n in per_file.items():
                self._files[path] = FileState(path, n)
            self._total = len(nodeids)
            self._path_width = min(max((len(p) for p in per_file), default=10), 48)

    def _announce_plan(self) -> None:
        if self._announced:
            return
        self._announced = True
        bits = [
            Text.assemble((str(self._total), "bold"), (" tests" if self._total != 1 else " test", "dim")),
            Text.assemble((str(len(self._files)), "bold"), (" files" if len(self._files) != 1 else " file", "dim")),
        ]
        deselected = len(self.stats.get("deselected", []))
        if deselected:
            bits.append(Text.assemble((str(deselected), "bold"), (" deselected", "dim")))
        if self._workers:
            bits.append(Text.assemble((str(len(self._workers)), "bold"), (" workers", "dim")))
        self._print(Text("   ") + Text(" · ", style="dim").join(bits))
        first = self.config.stash.get(ORDERED, None)
        if first:
            line = Text.assemble(("   ↯ first: ", "bold #facc15"))
            names = [Text.assemble((str(first[g]), "bold"), (f" {g}", "dim")) for g in GROUPS if first[g]]
            self._print(line + Text(" · ", style="dim").join(names))
        self._print()

    # -- running tests -----------------------------------------------------------------

    def pytest_runtestloop(self) -> None:
        return None

    def _file(self, nodeid: str) -> FileState:
        path = render.file_of(nodeid)
        fs = self._files.get(path)
        if fs is None:
            fs = self._files[path] = FileState(path, 0)
        return fs

    def pytest_runtest_logstart(self, nodeid: str, location: tuple) -> None:
        now = time.monotonic()
        self._compare = None
        with self._lock:
            if self._t_run is None:
                self._t_run = now
            self._running[nodeid] = now
            self._locations[nodeid] = location
            fs = self._file(nodeid)
            if fs.started is None:
                fs.started = now
        self._announce_plan()

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo):
        report = yield
        compare, self._compare = self._compare, None
        if not report.failed or call.excinfo is None:
            return report
        key = (report.nodeid, report.when)
        error = call.excinfo.value
        # a `==` caught earlier in the test (pytest.raises) mustn't be blamed for a later, different assert
        if compare is not None and isinstance(error, AssertionError) and " == " in str(error).split("\n", 1)[0]:
            # diffed now, while the operands are as the assertion saw them
            found = assert_diff.explain(*compare)
            if found is not None:
                self._diffs[key] = found
        if self._tbstyle in ("auto", "long"):
            with contextlib.suppress(Exception):
                self._tracebacks[key] = render.rich_traceback(
                    call.excinfo, self.console.width, brief=key in self._diffs
                )
        return report

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef: Any, request: pytest.FixtureRequest):
        spent = self._fixtures.setdefault((fixturedef.argname, fixturedef.scope), FixtureTime())
        started: list[float] = []

        def tearing_down() -> None:
            started.append(time.perf_counter())

        def torn_down() -> None:
            if started:
                spent.teardown += time.perf_counter() - started.pop()

        # finalizers run last-in first-out: these two end up around the fixture's own teardown
        fixturedef.addfinalizer(torn_down)
        t0 = time.perf_counter()
        try:
            return (yield)
        finally:
            spent.setup += time.perf_counter() - t0
            spent.count += 1
            fixturedef.addfinalizer(tearing_down)

    def pytest_assertrepr_compare(self, config: pytest.Config, op: str, left: Any, right: Any) -> None:
        # Only remembered: pytest still writes its own explanation, for --tb=short, xdist and the like.
        if op == "==":
            self._compare = (left, right)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._tests_ran = True
        category = self.config.hook.pytest_report_teststatus(report=report, config=self.config)[0]
        self._add_stats(category, [report])
        with self._lock:
            ts = self._tests.setdefault(report.nodeid, TestState())
            ts.duration += report.duration
            if category and ts.outcome not in render.FAILING:
                ts.outcome = category
            if report.failed:
                key = (report.nodeid, report.when)
                self._failures.append(Failure(report, self._tracebacks.pop(key, None), self._diffs.pop(key, None)))
            flaky = rerun.flaky(report) if report.when == "call" and report.passed else None
            if flaky is not None:
                self._flaky.append((report.nodeid, *flaky))
        if flaky is not None and self._verbose >= -1:
            self._print(self._flaky_line(report.nodeid, *flaky))
        if report.failed and self._verbose >= -1:
            line = Text.assemble(("  ✗ ", "bold red"), self._node(report.nodeid, self._crash_url(report)))
            if report.when != "call":
                line.append(f" ({report.when})", style="red")
            line.append("  " + self._crash(self._failures[-1]), style="dim red")
            self._print(line)

    def pytest_runtest_logfinish(self, nodeid: str, location: tuple) -> None:
        now = time.monotonic()
        with self._lock:
            self._running.pop(nodeid, None)
            ts = self._tests.setdefault(nodeid, TestState())
            if ts.finished:
                return
            ts.finished = True
            ts.outcome = ts.outcome or "passed"
            self._counts[ts.outcome] += 1
            self._done += 1
            fs = self._file(nodeid)
            fs.done += 1
            fs.categories.append(ts.outcome)
            fs.finished_at.append(now)
            if ts.outcome not in render.FAILING:
                self._last_hit = now
            broke = None
            if ts.outcome == "passed":
                self._combo += 1
                self._max_combo = max(self._max_combo, self._combo)
            elif ts.outcome in render.FAILING:
                if self._combo >= COMBO_SHOWN:
                    self._combo_broken = (self._combo, now)
                    broke = self._combo
                self._combo = 0
            combo = self._combo
            fs.counts[ts.outcome] += 1
            fs.duration += ts.duration
            fs.total = max(fs.total, fs.done)
            file_done = fs.done >= fs.total and not fs.flushed
            if file_done:
                fs.flushed = True
        if self._player is not None:
            self._sound_for(ts.outcome, combo, broke)
        if self._verbose > 0:
            self._print(
                Text.assemble(
                    "    ",
                    (render.glyph(ts.outcome), render.style(ts.outcome)),
                    " ",
                    self._node(nodeid),
                    ("  " + render.fmt_dur(ts.duration), "dim"),
                )
            )
        if file_done and self._verbose >= 0:
            self._print(self._file_line(fs))

    def _sound_for(self, outcome: str, combo: int, broke: int | None) -> None:
        player = self._player
        level = sound.milestone(combo) if outcome == "passed" else None
        if level is not None:
            player.play(f"combo{level}")
        elif outcome in render.FAILING and self._fight is not None:
            player.play("hurt")
        elif broke:
            player.play("combo_breaker")
        elif self._fight is not None:
            player.hit(crit=combo >= COMBO_SHOWN)
        if self._fight is not None:
            hp = max(self._total, self._done)
            left = hp - self._hits()
            phase = Fight(self._fight.name, self._fight.sprite, hp).phase(left)
            if phase > self._boss_phase and left > 0:
                player.play("roar")
            self._boss_phase = max(phase, self._boss_phase)

    def _flaky_line(self, nodeid: str, attempts: int, first: str) -> Text:
        return Text.assemble(
            ("  〰 ", "bold yellow"),
            self._node(nodeid, self._test_url(nodeid)),
            (f"  flaky, passed on try {attempts}", "yellow"),
            (f" · {first.removeprefix('AssertionError: ')}" if first else "", "dim"),
        )

    def _file_line(self, fs: FileState, now: float | None = None) -> Text:
        live = now is not None
        failing = any(fs.counts[c] for c in render.FAILING)
        if live:
            cat = None
        elif failing:
            cat = "failed"
        elif fs.done < fs.total:
            cat = None
        elif fs.counts and set(fs.counts) <= {"skipped"}:
            cat = "skipped"
        else:
            cat = "passed"
        if live:
            icon = fs.spinner.render(now)
            icon.stylize("red" if failing else "cyan")
        elif cat is None:
            icon = Text("◌", style="dim")
        else:
            icon = Text(render.glyph(cat), style=f"bold {render.style(cat)}")
        width = max(10, min(40, self.console.width - self._path_width - 34))
        count = f"{fs.done}/{fs.total}" if live or fs.done < fs.total else str(fs.total)
        clock = render.fmt_clock(now - fs.started) if live else render.fmt_dur(fs.duration)
        line = Text.assemble(
            "  ",
            icon,
            " ",
            render.linked(render.path_text(fs.path, self._path_width), self._url(fs.path)),
            "  ",
            render.strip(fs.categories, fs.total, width, [now - t for t in fs.finished_at] if live else None),
            (f" {count:>7}", "dim"),
            (f" {clock:>7}", "dim"),
        )
        bad = render.counts_text(Counter({c: n for c, n in fs.counts.items() if c != "passed"}))
        if bad:
            line.append("  ")
            line.append_text(bad)
        return line

    # -- the live view ------------------------------------------------------------------

    def _render_live(self):
        now = time.monotonic()
        with self._lock:
            if not self._planned or self._t_run is None:
                n = self._total if self._planned else self._numcollected
                text = Text.assemble(("collecting", "bold"), ("… ", "dim"), (str(n), "bold"), (" tests", "dim"))
                if self._status:
                    text.append(f"   {self._status}", style="dim")
                self._collect_spinner.update(text=text)
                return Group(Text(""), self._collect_spinner)

            failing = sum(self._counts[c] for c in render.FAILING) + len(self._collect_errors)
            parts: list = []

            active = sorted(
                (fs for fs in self._files.values() if fs.started is not None and not fs.flushed),
                key=lambda fs: fs.started,
            )
            for fs in active[:MAX_ACTIVE_FILES]:
                parts.append(self._file_line(fs, now))
            if active and len(active) > MAX_ACTIVE_FILES:
                parts.append(Text(f"  … {len(active) - MAX_ACTIVE_FILES} more files running", style="dim"))

            slow = sorted((t0, nodeid) for nodeid, t0 in self._running.items() if now - t0 >= SLOW_RUNNING)
            if len(self._workers) > 1:
                parts += [Text(""), *self._worker_lines(now)]
                slow = []  # the worker lines already time what's running
            show_file = len(active) > 1
            for t0, nodeid in slow[:MAX_RUNNING_TESTS]:
                elapsed = now - t0
                st = "bold red" if elapsed >= 5 else "yellow" if elapsed >= 1 else "dim"
                name = (
                    self._node(nodeid)
                    if show_file
                    else render.linked(Text(render.test_name(nodeid)), self._test_url(nodeid))
                )
                parts.append(Text.assemble("     ", ("↳ ", "dim"), name, ("  ⏱ " + render.fmt_clock(elapsed), st)))
                if elapsed >= hang.HANG and not self._workers:
                    where = self._where_stuck()
                    if where is not None:
                        line = Text("       ") + where
                        line.no_wrap, line.overflow = True, "ellipsis"
                        parts.append(line)

            total = max(self._total, self._done, 1)
            elapsed = now - self._t_run
            eta = elapsed / self._done * (total - self._done) if self._done else None
            overall = Table.grid(padding=(0, 1), expand=True)
            overall.add_column(width=1)
            overall.add_column(ratio=1)
            for _ in range(4):
                overall.add_column(justify="right", no_wrap=True)
            overall.add_row(
                "",
                render.GlowBar(self._done, total, render.GRADIENTS["red" if failing else "green"], now),
                Text.assemble(
                    (str(self._done), "bold"), (f"/{total}", "dim"), (f"  {self._done * 100 // total}%", "bold")
                ),
                render.counts_text(self._counts),
                Text("⏱ " + render.fmt_clock(elapsed), style="dim"),
                Text("eta " + (render.fmt_clock(eta) if eta is not None else "…"), style="dim"),
            )
            if self._fight is not None:
                self._fight.hp = total
                parts += [Text(""), arena(self._fight, total - self._hits(), failing, now, self._last_hit, self._combo)]
            parts += [Text(""), overall]
            combo = self._combo_line(now)
            if combo is not None:
                parts.append(combo)
            if self._status and self._verbose > 0:
                parts.append(Text(self._status, style="dim"))
            return Group(*parts)

    # -- debugging --------------------------------------------------------------------

    def pytest_enter_pdb(self, config: pytest.Config, pdb: Any) -> None:
        self._stop_live()

    def pytest_leave_pdb(self, config: pytest.Config, pdb: Any) -> None:
        self._start_live()

    def pytest_internalerror(self, excrepr: Any) -> bool:
        self._stop_live()
        return super().pytest_internalerror(excrepr)

    def pytest_unconfigure(self) -> None:
        self._stop_live()
        super().pytest_unconfigure()
        self.console.file.flush()

    # -- the final report -------------------------------------------------------------

    def pytest_terminal_summary(self) -> None:
        # Our own summary is printed around the hook; other plugins still get their turn.
        pass

    @pytest.hookimpl(wrapper=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        # A wrapper, like the stock reporter: report after every other plugin has finished.
        result = yield
        self._report(session, exitstatus)
        return result

    def _report(self, session: pytest.Session, exitstatus: int) -> None:
        self._stop_live()
        self._announce_plan()
        for fs in self._files.values():
            if fs.done and not fs.flushed and self._verbose >= 0:
                fs.flushed = True
                self._print(self._file_line(fs))

        show = not getattr(self, "no_summary", False)
        if show:
            self._print_collect_errors()
            self._print_failures()
            self._print_warnings()
        self._coverage = cov.collect(self.config)
        if self._coverage is None:
            for content in self._suppressed:
                self._print(Text(content.strip(), style="bold red"))
        if exitstatus in SUMMARY_EXIT_CODES:
            self.config.hook.pytest_terminal_summary(terminalreporter=self, exitstatus=exitstatus, config=self.config)
        self._print_coverage()
        get_max = getattr(self, "_get_max_warnings", None)
        max_warnings = get_max() if get_max else None
        if max_warnings is not None and session.exitstatus == pytest.ExitCode.OK:
            n = len(self.stats.get("warnings", []))
            if n > max_warnings:
                session.exitstatus = pytest.ExitCode.MAX_WARNINGS_ERROR
                self._print(Text(f"Tests pass, but maximum allowed warnings exceeded: {n} > {max_warnings}", "red"))
        self._duration = time.monotonic() - self._t_start
        self._shiny = bool(
            self._done and not self._failing() and exitstatus == pytest.ExitCode.OK and random.random() < SHINY_ODDS
        )
        if self._boss_won() and exitstatus == pytest.ExitCode.OK:
            self._loot = drop()
        self._celebrations(exitstatus)
        if show:
            self._print_slowest()
            self._print_fixtures()
            self._print_insights()
            self._print_achievements()
            self._print_changes()
        if session.shouldfail:
            self._print(Text(f"  ! {session.shouldfail}", style="bold red"))
        elif session.shouldstop:
            self._print(Text(f"  ! {session.shouldstop}", style="bold red"))
        if exitstatus == pytest.ExitCode.INTERRUPTED and getattr(self, "_keyboardinterrupt_memo", None) is not None:
            crash = self._keyboardinterrupt_memo.reprcrash
            where = f" at {crash.path}:{crash.lineno}" if crash is not None else ""
            self._print(Text(f"  ◌ interrupted{where}", style="bold yellow"))
            self._keyboardinterrupt_memo = None
        self._print_verdict(session, exitstatus)
        self._save_history(exitstatus)

    def _rule(self, title: str, style: str) -> None:
        self.console.print()
        self._print(render.fade_rule(title, render.GRADIENTS.get(style, (style,)), self.console.width))

    def _print_collect_errors(self) -> None:
        if not self._collect_errors:
            return
        self._rule("collection errors", "red")
        for report in self._collect_errors:
            self.console.print(Text.assemble(("✗ ", "bold red"), self._node(report.nodeid or ".")))
            self.console.print(render.longrepr_text(str(report.longreprtext)))

    def _print_failures(self) -> None:
        if not self._failures or self._tbstyle == "no":
            return
        groups = group_failures(self._failures)
        distinct = f" · {len(groups)} distinct" if len(groups) < len(self._failures) else ""
        self._rule(f"failures ({len(self._failures)}{distinct})", "red")
        for i, (failure, *same) in enumerate(groups):
            report = failure.report
            title = Text.assemble(("✗ ", "bold red"), self._node(report.nodeid, self._crash_url(report)))
            if report.when != "call":
                title.append(f"  error in {report.when}", style="red")
            if i:
                self.console.print()
            self.console.print(title)
            if i < MAX_BLAMES:
                who = self._blame(report)
                if who is not None:
                    self._print(Text.assemble(("  ↳ ", "dim"), (who, "dim italic")))
                memory = self._memory(report)
                if memory is not None:
                    self._print(Text.assemble(("  ↳ ", "dim"), (memory, "dim italic")))
            if failure.traceback is not None:
                render.shorten_paths(failure.traceback, str(self.config.invocation_params.dir))
                self.console.print(failure.traceback)
            else:
                self.console.print(Panel(render.longrepr_text(str(report.longreprtext)), border_style="red"))
            if failure.diff is not None and self._tbstyle in ("auto", "long"):
                title = Text.assemble(" ", ("− left", assert_diff.LEFT), "  ", ("+ right", assert_diff.RIGHT), " ")
                self.console.print(render.GlowPanel(failure.diff.render(), render.GRADIENTS["glow"], title))
            if same:
                self._print_same(same)
            for name, content in report.sections:
                if not content.strip():
                    continue
                lines = content.rstrip().splitlines()
                if len(lines) > 30:
                    lines = [f"… {len(lines) - 30} more lines", *lines[-30:]]
                self.console.print(
                    Panel(
                        Text("\n".join(lines)),
                        title=Text(name.lower(), style="dim"),
                        title_align="left",
                        border_style="grey37",
                        padding=(0, 1),
                    )
                )

    def _url(self, path: str, line: int | None = None) -> str | None:
        """A link to open ``path`` (absolute, or from the rootdir) at ``line``."""
        if self._link is None or not path:
            return None
        path = os.path.abspath(os.path.join(str(self.config.rootpath), path)).replace(os.sep, "/")
        if not path.startswith("/"):
            path = "/" + path  # C:/x → /C:/x
        return self._link.format(path=urllib.parse.quote(path), line=line or 1)

    def _crash_url(self, report: Any) -> str | None:
        crash = getattr(report.longrepr, "reprcrash", None)
        if crash is None:
            return self._test_url(report.nodeid)
        return self._url(str(crash.path), crash.lineno)

    def _test_url(self, nodeid: str) -> str | None:
        if self._link is None:
            return None
        location = self._locations.get(nodeid)
        if location is None:
            return self._url(nodeid.split("::", 1)[0])
        path, line = location[0], location[1]
        return self._url(path, line + 1 if line is not None else None)

    def _node(self, nodeid: str, url: str | None = None) -> Text:
        return render.linked(render.nodeid_text(nodeid), url or self._test_url(nodeid))

    def _print_same(self, same: list) -> None:
        noun = "test" if len(same) == 1 else "tests"
        self.console.print(Text.assemble(("  ⧉ ", "bold red"), (f"the same failure in {len(same)} more {noun}", "red")))
        for failure in same[:MAX_GROUPED_IDS]:
            self.console.print(
                Text.assemble("    ", self._node(failure.report.nodeid, self._crash_url(failure.report)))
            )
        if len(same) > MAX_GROUPED_IDS:
            self.console.print(Text(f"    … and {len(same) - MAX_GROUPED_IDS} more", style="dim"))

    def _crash(self, failure: Failure) -> str:
        if failure.diff is not None and failure.diff.summary:
            return failure.diff.summary
        return render.crash_message(failure.report)

    def _blame(self, report: pytest.TestReport) -> str | None:
        """git blame for the deepest frame of the failure that lives in the project."""
        root = str(self.config.rootpath)
        here = str(self.config.invocation_params.dir)
        longrepr = report.longrepr
        chain = getattr(longrepr, "chain", None)
        tb = chain[-1][0] if chain else getattr(longrepr, "reprtraceback", None)
        for entry in reversed(getattr(tb, "reprentries", None) or []):
            loc = getattr(entry, "reprfileloc", None)
            if loc is None:
                continue
            path = os.path.normpath(os.path.join(here, str(loc.path)))
            if not path.startswith(root + os.sep) or "site-packages" in path.split(os.sep):
                continue
            self._blamed_paths.add(os.path.relpath(path, root))
            found = blame(path, loc.lineno)
            if found is None:
                return None
            if found.when is not None:
                age = time.time() - found.when
                self._oldest_blame = max(age, self._oldest_blame or 0)
            return f"line {loc.lineno} {describe(found)}"
        return None

    def _memory(self, report: Any) -> str | None:
        """What the history remembers of a failing test: how long it's been red, and since which commit."""
        if not self._history.enabled or not report.nodeid:
            return None
        outcomes = self._history.outcomes(report.nodeid)
        if not outcomes:
            return None
        parts = []
        streak = self._history.failing_streak(report.nodeid) + 1
        if streak >= 2:
            parts.append(f"failing {streak} runs in a row")
        last = self._history.last_pass(report.nodeid)
        if last is not None:
            when, commit = last
            text = f"last passed {ago(time.time() - when)}"
            if commit:
                since = commits_since(str(self.config.rootpath), commit)
                if since == 0:
                    text += ", on this very commit"
                elif since:
                    text += f" at {commit[:7]}, {since} commit{'s' if since != 1 else ''} ago"
                else:
                    text += f" at {commit[:7]}"  # rebased away, or another branch
            parts.append(text)
        elif "P" not in outcomes:
            parts.append("never passed in the runs glow remembers")
        return " · ".join(parts) or None

    def _print_warnings(self) -> None:
        warnings = self.stats.get("warnings", [])
        if not warnings:
            return
        self._rule(f"warnings ({len(warnings)})", "yellow")
        grouped: dict[str, list] = {}
        for w in warnings:
            grouped.setdefault(w.message.strip(), []).append(w)
        for message, items in list(grouped.items())[:8]:
            head = _WARNING_LOCATION.sub("", message.splitlines()[0]) if message else ""
            category, _, text = head.partition(": ")
            where = items[0].nodeid or (
                f"{items[0].fslocation[0]}:{items[0].fslocation[1]}" if items[0].fslocation else ""
            )
            line = Text.assemble(("  ⚠ ", "yellow"), (f"{category}: ", "bold yellow"), (text, "yellow"))
            if len(items) > 1:
                line.append(f"  ×{len(items)}", style="bold yellow")
            self._print(line)
            if where:
                self._print(Text(f"    {where}", style="dim"))
        if len(grouped) > 8:
            self._print(Text(f"  … {len(grouped) - 8} more kinds of warnings", style="dim"))

    def _print_coverage(self) -> None:
        result = self._coverage
        if result is None:
            return
        if result.show_table and result.files:
            self._rule("coverage", "cyan")
            files = [f for f in result.files if not (result.skip_covered and f.percent >= 100)]
            hidden = 0
            if len(files) > 25:
                partial = sorted((f for f in files if f.percent < 100), key=lambda f: f.percent)[:25]
                hidden, files = len(files) - len(partial), partial
            width = min(max([len(f.path) for f in files] + [5]), 48)
            for f in files:
                line = Text.assemble(
                    "  ",
                    render.path_text(f.path, width),
                    "  ",
                    cov.bar(f.percent, 20),
                    (f" {cov.fmt_percent(f.percent, 0):>4}", f"bold {cov.color(f.percent)}"),
                )
                before = self._history.coverage.get(f.path)
                if before is not None and abs(f.percent - before) >= 0.5:
                    up = f.percent > before
                    line.append(
                        f"  {'▲' if up else '▼'} {f.percent - before:+.0f}%", style="green" if up else "bold red"
                    )
                if f.missing:
                    line.append(f"  {len(f.missing)} missing", style="dim")
                    if result.show_missing:
                        line.append(f"  {cov.ranges(f.missing)}", style="cyan")
                self._print(line)
            if hidden:
                self._print(Text(f"  … {hidden} fully covered files not shown", style="dim"))
            total = Text.assemble(
                "  ",
                ("total".ljust(width), "bold"),
                "  ",
                cov.bar(result.total, 20, result.fail_under),
                (
                    f" {cov.fmt_percent(result.total, result.precision):>4}",
                    f"bold {cov.color(result.total, result.fail_under)}",
                ),
            )
            self.console.print()
            self._print(total)
        for note in result.notes:
            self._print(Text(f"  {note}", style="dim"))

    def _coverage_line(self) -> Text | None:
        result = self._coverage
        if result is None:
            return None
        st = cov.color(result.total, result.fail_under)
        line = Text.assemble(
            ("☂ ", st), (cov.fmt_percent(result.total, result.precision), f"bold {st}"), (" covered", "dim")
        )
        before = self._history.last_coverage()
        if before is not None:
            delta = result.total - before
            if abs(delta) < 0.05:
                line.append("  · unchanged", style="dim")
            else:
                line.append(
                    f"  · {'▲' if delta > 0 else '▼'} {delta:+.1f}% vs last run",
                    style="green" if delta > 0 else "yellow",
                )
        if result.fail_under is not None:
            if result.failed:
                line.append(f"  · below the required {result.fail_under:g}%", style="bold red")
            else:
                line.append(f"  · meets the required {result.fail_under:g}%", style="dim")
        return line

    def _print_slowest(self) -> None:
        finished = [(ts.duration, nodeid) for nodeid, ts in self._tests.items() if ts.finished]
        slowest = [item for item in sorted(finished, reverse=True)[:5] if item[0] >= 0.1]
        if not slowest or slowest[0][0] < 0.2:
            return
        self.console.print()
        self.console.print(Text("  slowest", style="bold dim"))
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(no_wrap=True, overflow="ellipsis")
        table.add_column(no_wrap=True)
        table.add_column(no_wrap=True)
        top = slowest[0][0]

        def trend(nodeid: str, dur: float) -> Text:
            past = self._history.durations(nodeid)[-11:]
            return render.spark([*past, dur], render.GRADIENTS["cyan"]) if len(past) >= 2 else Text()

        for dur, nodeid in slowest:
            st = "bold red" if dur >= 5 else "yellow" if dur >= 1 else "default"
            compare = Text()
            median = self._history.median_duration(nodeid)
            if median and dur >= 0.1 and abs(dur - median) / median >= 0.25:
                pct = (dur - median) / median * 100
                compare = Text(f"{'▲' if pct > 0 else '▼'} {pct:+.0f}% vs usual", style="red" if pct > 0 else "green")
            stops = render.GRADIENTS["red" if dur >= 5 else "yellow" if dur >= 1 else "cyan"]
            table.add_row(
                Text("  " + render.fmt_dur(dur), style=st),
                render.glow_bar(dur, top, 12, stops),
                self._node(nodeid),
                trend(nodeid, dur),
                compare,
            )
        self.console.print(table)

    def _print_fixtures(self) -> None:
        ranked = sorted(self._fixtures.items(), key=lambda item: -item[1].total)[:5]
        if not ranked or ranked[0][1].total < 0.2:
            return
        self.console.print()
        self.console.print(Text("  slowest fixtures", style="bold dim"))
        ranked = [(key, spent) for key, spent in ranked if spent.total >= 0.05]
        top = ranked[0][1].total
        name_width = max(len(name) for (name, _), _ in ranked)
        for (name, scope), spent in ranked:
            details = [] if scope == "function" else [scope]
            if spent.count > 1:
                details.append(f"×{spent.count}, {render.fmt_dur(spent.total / spent.count)} each")
            if spent.teardown >= 0.01:
                details.append(f"setup {render.fmt_dur(spent.setup)}, teardown {render.fmt_dur(spent.teardown)}")
            share = spent.total / self._duration if self._duration else 0
            if share >= 0.2:
                details.append(f"{share:.0%} of the run")
            st = "bold red" if spent.total >= 5 else "yellow" if spent.total >= 1 else "default"
            # on a narrow terminal, only the details at the end get cut
            line = Text.assemble(
                (f"  {render.fmt_dur(spent.total):>7}  ", st),
                render.glow_bar(spent.total, top, 12, render.GRADIENTS["glow"]),
                (f"  {name:<{name_width}}  ", "bold"),
                (" · ".join(details), "dim"),
            )
            self._print(line)

    def _print_insights(self) -> None:
        if not self._history.enabled:
            return
        fixed, broken, flaky = [], [], []
        for nodeid, ts in self._tests.items():
            if not ts.finished:
                continue
            last = self._history.last_outcome(nodeid)
            now_failing = ts.outcome in render.FAILING
            if last in ("F", "E") and ts.outcome == "passed":
                fixed.append(nodeid)
            elif last == "P" and now_failing:
                broken.append(nodeid)
            trail = self._history.outcomes(nodeid) + {"passed": "P", "failed": "F", "error": "E"}.get(ts.outcome, "")
            if is_flaky(trail):
                flaky.append((nodeid, trail))
        slower = self._slower_than_usual()
        if not (fixed or broken or flaky or slower):
            return
        self.console.print()
        for icon, st, title, items in (("✨", "green", "fixed", fixed), ("💥", "red", "newly failing", broken)):
            for nodeid in items[:5]:
                self._print(Text.assemble(f"  {icon} ", (f"{title}  ", f"bold {st}"), self._node(nodeid)))
            if len(items) > 5:
                self._print(Text(f"     … and {len(items) - 5} more {title}", style="dim"))
        for nodeid, trail in flaky[:5]:
            self._print(
                Text.assemble(
                    "  〰 ",
                    ("flaky  ", "bold yellow"),
                    self._node(nodeid),
                    "  ",
                    render.outcome_trail(trail[-10:]),
                )
            )
        for nodeid, dur, usual in slower[:5]:
            self._print(
                Text.assemble(
                    "  🐢 ",
                    ("slower  ", "bold yellow"),
                    self._node(nodeid),
                    ("  " + render.fmt_dur(dur), "bold yellow"),
                    (f", usually {render.fmt_dur(usual)} ", "dim"),
                    (f"×{dur / usual:.1f}", "yellow"),
                )
            )
        if len(slower) > 5:
            self._print(Text(f"     … and {len(slower) - 5} more slower than usual", style="dim"))

    def _where_stuck(self) -> Text | None:
        frame = hang.thread_frame(getattr(self, "_main_thread", None))
        spots = hang.stuck_at(frame, str(self.config.rootpath))
        mine = spots[0]
        where = hang.describe(spots, str(self.config.invocation_params.dir))
        if where is not None and mine is not None:
            render.linked(where, self._url(mine.path, mine.line))
        return where

    def _hits(self) -> int:
        return sum(n for c, n in self._counts.items() if c not in render.FAILING)

    def _worker_lines(self, now: float) -> list[Text]:
        lines = []
        for worker in sorted(self._workers, key=lambda w: (len(w), w))[:MAX_WORKERS_SHOWN]:
            spinner = self._worker_spinners.setdefault(worker, Spinner("dots", style="cyan"))
            running = self._worker_now.get(worker)
            line = Text.assemble("  ", (f"{worker:<4}", "bold"), " ")
            if running is None:
                line.append("·", style="dim")
            else:
                line.append_text(spinner.render(now))
            line.append(f" {self._worker_done[worker]:>4} done  ", style="dim")
            if running is None:
                line.append("idle", style="dim")
            else:
                nodeid, t0 = running
                elapsed = now - t0
                st = "bold red" if elapsed >= 5 else "yellow" if elapsed >= 1 else "dim"
                line.append_text(self._node(nodeid))
                line.append("  ⏱ " + render.fmt_clock(elapsed), style=st)
            lines.append(line)
        if len(self._workers) > MAX_WORKERS_SHOWN:
            lines.append(Text(f"  … {len(self._workers) - MAX_WORKERS_SHOWN} more workers", style="dim"))
        return lines

    def _combo_line(self, now: float) -> Text | None:
        broken = self._combo_broken
        if broken is not None and now - broken[1] < COMBO_BROKEN and self._combo < COMBO_SHOWN:
            return Text.assemble("  ", ("💔 COMBO BREAKER", "bold red"), (f"  ×{broken[0]}", "red"))
        if self._combo < COMBO_SHOWN:
            return None
        line = Text("  ⚡ ")
        line.append_text(render.gradient_text(f"×{self._combo} COMBO", render.combo_stops(self._combo)))
        if self._max_combo > self._combo:
            line.append(f"  best ×{self._max_combo}", style="dim")
        return line

    def _print_changes(self) -> None:
        """On a red run: what changed in git since the last green one."""
        if not self._failing() or not self._history.enabled:
            return
        green = self._history.last_green()
        if green is None:
            return
        root = str(self.config.rootpath)
        changed = changed_since(root, green["g"], green.get("t", 0))
        if changed is None:
            return
        when = ago(time.time() - green.get("t", time.time()))
        self.console.print()
        if not changed:
            self._print(
                Text.assemble(
                    "  🔍 ",
                    ("nothing changed", "bold"),
                    (f" in git since the last green run, {when} — flaky, environment or data?", "dim"),
                )
            )
            return
        self._print(Text.assemble("  🔍 ", ("changed since the last green run", "bold"), (f", {when}", "dim")))
        suspects = self._blamed_paths | {render.file_of(f.report.nodeid) for f in self._failures}
        suspects |= {render.file_of(r.nodeid) for r in self._collect_errors if r.nodeid}
        changed.sort(key=lambda p: p not in suspects)  # stable: the suspects first, newest first within
        for path in changed[:8]:
            line = Text("     ") + render.linked(render.path_text(path), self._url(path))
            if path in suspects:
                line.append("  ← failing here", style="bold red")
            self._print(line)
        if len(changed) > 8:
            self._print(Text(f"     … and {len(changed) - 8} more", style="dim"))

    def _rerun_command(self) -> str | None:
        """What to type to run just the failures again: their ids, or --lf when there are many."""
        nodeids = list(dict.fromkeys(f.report.nodeid for f in self._failures if f.report.nodeid))
        if not nodeids:
            return None
        if len(nodeids) > MAX_RERUN_IDS and self._history.enabled:
            return "pytest --lf"
        root, here = str(self.config.rootpath), str(self.config.invocation_params.dir)
        args = []
        for nodeid in nodeids[:MAX_RERUN_IDS]:
            path, sep, rest = nodeid.partition("::")
            args.append(shlex.quote(os.path.relpath(os.path.join(root, path), here) + sep + rest))
        more = len(nodeids) - MAX_RERUN_IDS
        return "pytest " + " ".join(args) + (f"  # +{more} more" if more > 0 else "")

    def _slower_than_usual(self) -> list[tuple[str, float, float]]:
        out = []
        for nodeid, ts in self._tests.items():
            if not ts.finished or ts.outcome not in ("passed", "failed"):
                continue
            usual = self._history.median_duration(nodeid)
            if usual and ts.duration >= usual * SLOWER and ts.duration - usual >= 0.1:
                out.append((nodeid, ts.duration, usual))
        return sorted(out, key=lambda t: t[1] / t[2], reverse=True)

    def _failing(self) -> int:
        failing = sum(self._counts[c] for c in render.FAILING) + len(self._collect_errors)
        if self._coverage is not None and self._coverage.failed:
            failing += 1
        return failing

    def _celebrations(self, exitstatus: int) -> None:
        """Personal bests and achievements, settled before anything is printed about them."""
        history = self._history
        if not history.enabled or not self._done or exitstatus == pytest.ExitCode.INTERRUPTED:
            return
        ok = not self._failing() and exitstatus == pytest.ExitCode.OK
        best = history.personal_best(self._done)
        if ok and best is not None and self._duration < best:
            self._new_pb = best
        fixed_streaks = [
            history.failing_streak(nodeid)
            for nodeid, ts in self._tests.items()
            if ts.finished and ts.outcome == "passed"
        ]
        result = self._coverage
        facts = ach.RunFacts(
            ok=ok,
            hour=self._hour,
            weekday=self._weekday,
            oldest_blame=self._oldest_blame,
            max_combo=self._max_combo,
            boss_slain=self._fight is not None and ok and self._done >= 100,
            shiny=self._shiny,
            counts=Counter(self._counts),
            done=self._done,
            warnings=len(self.stats.get("warnings", [])),
            prior_runs=history.runs,
            green_streak=history.greens + 1 if ok else 0,
            new_pb=self._new_pb is not None,
            longest_fixed_streak=max(fixed_streaks, default=0),
            coverage_files=[(f.statements, f.percent) for f in result.files] if result else [],
            coverage_total=result.total if result else None,
            fail_under=result.fail_under if result else None,
            precision=result.precision if result else 0,
        )
        now = round(time.time())
        for a in ach.earned(facts):
            if a.key not in history.achievements:
                history.achievements[a.key] = now
                self._unlocked.append(a)
        self._fixed = sum(1 for streak in fixed_streaks if streak)
        gained = progress.xp_for(
            passed=self._counts.get("passed", 0),
            ok=ok,
            max_combo=self._max_combo,
            fixed=self._fixed,
            boss_won=self._boss_won(),
            shiny=self._shiny,
        )
        self._xp = (history.xp, gained)

    def _boss_won(self) -> bool:
        return self._fight is not None and self._done > 0 and not self._failing()

    def _leveled_up(self) -> bool:
        if self._xp is None:
            return False
        before, gained = self._xp
        return progress.level_of(before + gained)[0] > progress.level_of(before)[0]

    def _print_achievements(self) -> None:
        if not self._unlocked:
            return
        self.console.print()
        for a in self._unlocked:
            self._print(
                Text.assemble(
                    "  🏅 ",
                    render.gradient_text("achievement unlocked", render.GRADIENTS["glow"]),
                    "  ",
                    (a.title, "bold"),
                    ("  " + a.blurb, "dim"),
                )
            )
        got = len(self._history.achievements)
        self._print(Text(f"     {got}/{len(ach.ALL)} unlocked in this project", style="dim"))

    def _print_verdict(self, session: pytest.Session, exitstatus: int) -> None:
        failing = self._failing()
        if exitstatus == pytest.ExitCode.INTERRUPTED:
            icon, word, st = "◌", "interrupted", "yellow"
        elif failing or exitstatus not in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
            icon, word, st = "✗", "failed", "red"
        elif exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED or not self._done:
            icon, word, st = "∅", "no tests ran", "grey50"
        else:
            icon, word, st = "✓", "all green", "green"
        ok = word == "all green"
        if ok and self._flaky:
            icon, word, st = "〰", "green, but flaky", "yellow"
        elif ok and self._shiny:
            icon, word, st = "✦", "shiny ✦", "gold"

        duration = self._duration
        counts = Counter(self._counts)
        extra = {
            "collection error": (len(self._collect_errors), "red"),
            "flaky": (len(self._flaky), "yellow"),
            "warning": (len(self.stats.get("warnings", [])), "yellow"),
            "deselected": (len(self.stats.get("deselected", [])), "grey50"),
        }
        stops = render.GRADIENTS[st]
        line1 = Text.assemble(
            render.gradient_text(f" {icon} {word.upper()} ", stops, background=True),
            "  ",
            render.counts_text(counts, compact=False, extra=extra),
        )
        egg = EASTER_EGGS.get(counts.get("passed", 0))
        if egg:
            line1.append(f"  {egg}", style="dim italic")
        if self._shiny:
            line1.append("  a 1-in-500 run ✨", style="italic #fde68a")
        inner = max(10, self.console.width - 4)
        bar = render.proportion_bar(counts, inner) if counts else Text("━" * inner, style="grey30")
        if self._shiny:
            bar = render.glow_bar(1, 1, inner, stops)

        line3 = Text.assemble(("⏱ ", "dim"), (render.fmt_dur(duration), "bold"))
        prev = self._history.last_comparable_run(self._done) if self._done else None
        if prev and exitstatus != pytest.ExitCode.INTERRUPTED:
            delta = duration - prev.get("d", duration)
            if abs(delta) < 0.05 or abs(delta) / max(prev.get("d", 1), 1e-9) < 0.05:
                line3.append("  · same pace as last run", style="dim")
            elif delta < 0:
                line3.append(f"  · ▼ {render.fmt_dur(-delta)} faster than last run", style="green")
            else:
                line3.append(f"  · ▲ {render.fmt_dur(delta)} slower than last run", style="yellow")
        if self._workers:
            line3.append(f"  · {len(self._workers)} workers", style="dim")
        if self._max_combo >= 25:
            line3.append("  · ⚡ ")
            line3.append_text(
                render.gradient_text(f"max combo ×{self._max_combo}", render.combo_stops(self._max_combo))
            )
        if self._new_pb is not None:
            line3.append("  · ")
            line3.append_text(render.gradient_text("🏆 new PB", ("#facc15", "#fb923c")))
            line3.append(f" ({render.fmt_dur(self._new_pb)} → {render.fmt_dur(duration)})", style="dim")

        lines = [line1, line3]
        if self._fight is not None and self._done:
            self._fight.hp = max(self._total, self._done)
            lines.append(
                outcome(
                    self._fight,
                    self._fight.hp - self._hits(),
                    failing,
                    self._hits(),
                    render.fmt_dur(duration),
                    exitstatus == pytest.ExitCode.INTERRUPTED,
                )
            )
            if self._loot is not None:
                collected = list(self._history.life.get("loot", [])) if self._history.enabled else None
                lines.append(loot_line(self._loot, collected))
        coverage_line = self._coverage_line()
        if coverage_line is not None:
            lines.append(coverage_line)
        if self._history.enabled and self._done and exitstatus != pytest.ExitCode.INTERRUPTED:
            runs = [*self._history.runs[-23:], {"d": duration, "ok": ok}]
            line4 = Text.assemble(("runs ", "dim"), render.sparkline(runs))
            streak = self._history.green_streak()
            if ok and streak >= 1:
                line4.append(f"  🔥 {streak + 1} green runs in a row", style="bold green")
            elif ok and self._history.runs:
                line4.append("  ✨ back to green", style="bold green")
            elif not ok and streak >= 3:
                line4.append(f"  a streak of {streak} green runs just ended", style="dim")
            elif not self._history.runs:
                line4.append("  first run here — history starts now", style="dim")
            lines.append(line4)
            if self._xp is not None:
                lines.append(progress.xp_line(*self._xp))

        self.console.print()
        if self._failures and not getattr(self, "no_summary", False):
            groups = group_failures(self._failures)
            for failure, *same in groups[:15]:
                report = failure.report
                where = "" if report.when == "call" else f" ({report.when})"
                line = Text.assemble(
                    ("  ✗ ", "bold red"), self._node(report.nodeid, self._crash_url(report)), (where, "red")
                )
                if same:  # before the message, which may get cut at the edge
                    line.append(f"  +{len(same)} more like this", style="bold red")
                line.append("  " + self._crash(failure), style="dim")
                self._print(line)
            if len(groups) > 15:
                rest = sum(map(len, groups[15:]))
                self._print(Text(f"    … and {rest} more", style="dim"))
            again = self._rerun_command()
            if again:
                self._print(Text.assemble(("  ↻ rerun  ", "bold cyan"), (again, "cyan")))
        if self._flaky and not getattr(self, "no_summary", False):
            for nodeid, attempts, first in self._flaky[:15]:
                self._print(self._flaky_line(nodeid, attempts, first))
        title = Text(f" pytest-glow {__version__} ", style="dim")

        def panel(reveal: float = 1.0, now: float | None = None) -> render.GlowPanel:
            shown = round(len(bar) * reveal)
            line2 = bar[:shown] + Text("━" * (len(bar) - shown), style=render._TRACK)
            if now is not None and shown:
                # the same sweeping highlight as the live bar, riding the bar while it fills
                for i in range(max(shown - 8, 0), shown):
                    glow = 1 - (shown - 1 - i) / 8
                    base = line2.get_style_at_offset(self.console, i).color
                    color = base.get_truecolor().hex if base is not None else "#ffffff"
                    line2.stylize(f"bold {render.blend(color, render._WHITE, glow * 0.7)}", i, i + 1)
            return render.GlowPanel(Group(lines[0], line2, *lines[1:]), stops, title)

        if self._live_enabled and not os.environ.get("CI"):
            confetti = None
            if self._new_pb is not None or self._unlocked or self._leveled_up() or self._shiny:
                confetti = render.Confetti(self.console.width)
            length = CELEBRATE if confetti else REVEAL

            def frame(elapsed: float):
                progress = 1 - (1 - min(elapsed / REVEAL, 1)) ** 3  # ease out
                view = panel(progress, elapsed if progress < 1 else None)
                return Group(confetti.frame(elapsed), view) if confetti else view

            with Live(frame(0.0), console=self.console, transient=True, refresh_per_second=60) as live:
                t0 = time.monotonic()
                while (elapsed := time.monotonic() - t0) < length:
                    live.update(frame(elapsed))
                    time.sleep(1 / 60)
        self.console.print(panel())
        if self._share:
            self._save_card(icon, word, stops, counts, lines[1:])
        if self._player is not None and self._done:
            self._player.play(self._final_sound(failing, exitstatus), bell=True)

    def _final_sound(self, failing: int, exitstatus: int) -> str:
        if exitstatus == pytest.ExitCode.INTERRUPTED:
            return "sad_trombone"
        if self._fight is not None:
            if failing >= HEARTS:
                return "game_over"
            if not failing:
                return "boss_down"
        if failing:
            return "sad_trombone"
        if self._shiny:
            return "shiny"
        if self._leveled_up():
            return "level_up"
        return "airhorn" if self._new_pb or self._unlocked else "level_clear"

    def _save_card(self, icon: str, word: str, stops: tuple, counts: Counter, details: list) -> None:
        card = share.Card(
            project=self.config.rootpath.name,
            icon=icon,
            word=word,
            stops=stops,
            counts=counts,
            details=[line for line in details if not line.plain.startswith("runs ")],  # sparkline: too noisy for a card
        )
        path = os.path.join(str(self.config.invocation_params.dir), self._share)
        try:
            share.save(card, path)
        except OSError as e:
            self._print(Text(f"  couldn't save the card: {e}", style="red"))
            return
        self._print(Text.assemble(("  ✦ ", "magenta"), ("card saved to ", "dim"), (self._share, "bold")))

    def _save_history(self, exitstatus: int) -> None:
        if not self._history.enabled or not self._done or exitstatus == pytest.ExitCode.INTERRUPTED:
            return
        results = {nodeid: (ts.outcome or "passed", ts.duration) for nodeid, ts in self._tests.items() if ts.finished}
        failing = self._failing()
        measured = None
        if self._coverage is not None:
            measured = (self._coverage.total, {f.path: f.percent for f in self._coverage.files})
        commit = head(str(self.config.rootpath))
        self._history.record(results, self._duration, ok=not failing, failed=failing, coverage=measured, commit=commit)
        self._history.tally(
            ok=not failing,
            counts=dict(self._counts),
            duration=self._duration,
            hour=self._hour,
            xp=self._xp[1] if self._xp else 0,
            max_combo=self._max_combo,
            fixed=self._fixed,
            shiny=self._shiny,
            boss=None if self._fight is None else "won" if self._boss_won() else "lost",
            loot=self._loot[0] if self._loot else None,
        )
        self._history.save()
