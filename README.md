# pytest-glow

A live, [rich](https://github.com/Textualize/rich)-powered reporter for pytest. Same tests, same
flags, same exit codes. You just get to watch them run instead of reading a row of dots.

![pytest-glow on a red run: live file bars, failures as they happen, grouped failures, slowest tests and fixtures, and the verdict](https://github.com/koskrub-15/pytest-glow/raw/main/docs/demo.gif)

## What you get

**While the tests run**
- a line per running file: a spinner, a segmented bar where every test lights up green, red or yellow, counts and a clock
- the test that's running right now, with a ticking timer once it gets slow, and after 3s the line it's stuck
  on, with the call it's waiting in (`⏳ api.py:6 fetch_user  replies.get(timeout=30)  → threading.py wait`)
- under pytest-xdist, a line per worker: what it's running, for how long, and how many tests it has done
- an overall progress bar with an ETA, which turns red the moment something fails
- failures as one-liners as soon as they happen, so you don't wait for the end of the run to see them
- a combo counter for passes in a row, heating up as it grows, and a COMBO BREAKER when one fails

**At the end**
- rich tracebacks: highlighted source, locals (without pytest's `@py_assert` noise), captured output
- diffs for failed `==` asserts on dicts, lists, sets, strings, numbers, dataclasses and namedtuples: only what
  changed, nested paths like `user.address.city`, changed characters lit up. The failure one-liners say it
  too: `role: 'user' → 'admin'` instead of `assert {'name': 'gra...active': True} == {...}`. Also under xdist
- for a failed `in`, the near misses: `'3 new messages'` not in the page, but `'3 new mesages'` at char 50;
  `'admin'` not in the roles, closest `[3] 'admins'`; `8080` not in the ports, closest `8081`. For `not in`,
  where it was found, lit up in its context
- failures that failed the same way (same place, same message) grouped under one traceback: a database
  that's down is one failure with "+39 more like this", not forty tracebacks
- warnings grouped by message, the slowest tests, a short list of what failed
- the slowest fixtures, with setup and teardown apart, per call, and their share of the run
- with `--glow-profile`, where the time goes: under each slow test `↳ test 12% · your code 61% · libs 27%
  (sqlalchemy)`, and for the whole run fixtures, tests, your code and libraries on one bar, with the
  libraries that take the most (`in fixtures: argon2 5.40s`). It samples the stack every 5 ms, so it costs
  about nothing; time in C code (a `sleep`, a socket, numpy) counts for the Python code that called it.
  On macOS it gets a look in only every ~45 ms, so a test needs half a second or so for a breakdown of its own
- paths you can click: tests, files and failures open in the editor (VS Code's terminal opens at the line)
- a verdict panel with the counts and a proportional bar
- the command to rerun just the failures (`pytest --lf` when there are many)

**While you work**
- `pytest --glow-watch`: reruns on every save, what failed last time and what you just changed first. The header
  says which files changed. Keys, no Enter needed: `f` only what failed, `p` only tests matching a `-k`
  pattern, `d` the failures again in pdb, enter everything, `q` quits
- `--glow-ff`: runs first what likely fails: what failed last time, the test files you're editing (or the ones
  named after a module you're editing: `test_cart.py` for `shop/cart.py`), new tests and flaky ones
- `--glow-rerun[=N]`: a failed test runs again, up to N times. One that then passes is called out as flaky with
  how it failed the first time, and the run is GREEN, BUT FLAKY rather than red. Works under xdist and in CI

**On GitHub Actions** the log stays plain pytest, and the run also lands on the run's page as a job summary:
the verdict, failures grouped with a link to the failing line at the commit and `==` diffs as one-liners,
flaky tests and the slowest ones. `PYTEST_GLOW_SUMMARY=0` or `glow_summary = false` turns it off.

**Across runs** (kept in `.pytest_cache`, nothing to set up)
- green streaks, and the tests that were just *fixed* or just *started failing*
- flaky tests, with their recent pass/fail trail
- "faster/slower than last run", tests that got slower than usual, a sparkline of recent runs
- on a red run, what changed in git since the last green one, with the files the failures point at first;
  and when nothing changed, a hint that it's likely flaky, the environment or data
- under each failure, what its history says: `red for 4 runs, same failure · passed 2 days ago at 3f9c2e1,
  5 commits back`. "a new failure" when it broke differently than last run, "on this commit" when it passed
  minutes ago on the very same commit (so it's your uncommitted change, or it's flaky)

**Pure showing off** (all of it remembered in `.pytest_cache` too)
- personal bests: the fastest green run for a given number of tests, `🏆 new PB` when you beat it
- achievements, each unlocked once per project: First Blood, Phoenix, Night Owl, Minimalist, Sniper,
  Speedrunner, Surgeon, Clean Sweep, Centurion, Friday Deploy, Archaeologist, Glass Cannon, Unstoppable,
  Boss Slayer, Shiny Hunter
- XP for every run (passes, green, combos, fixed tests, boss kills) and levels with titles, from Print
  Debugger to The One Who Runs pytest. A level up gets confetti and its own jingle
- one green run in 500 comes out ✦ SHINY ✦: gold verdict, sparkle, 250 bonus XP
- daily quests: three a day, the same all day ("fix 3 tests", "a ×50 combo", "red → green", "green before
  10am"…), with their progress in the verdict and XP when done. `PYTEST_GLOW_QUESTS=0` turns them off
- a burst of confetti over the verdict when you set a record or unlock something (never in CI or pipes)
- under each failure, who last touched the failing line and when, from `git blame`
- a duration sparkline next to each of the slowest tests, so you see the ones getting slower
- certain pass counts are acknowledged
- `--glow-boss`: the suite is a boss fight. Every test that doesn't fail is a hit on your project's nemesis
  (the same boss every time), every failure costs you one of three hearts. Below half its HP it gets
  ENRAGED, below a tenth it makes its LAST STAND, and once slain it drops loot: sixteen items, common to
  legendary, to collect per project
- `pytest --glow-wrapped`: your project's year-in-review. Runs, time spent, green rate, level, records, a hall
  of shame (failed the most, flakiest, slowest), the hours you test at, loot and achievements. Runs no tests
- `--glow-share`: the run as an SVG card, ready to post
- `--glow-sound`: 8-bit sounds, synthesized on the fly (nothing to license): a power-up at combo 10, 25, 50,
  100…, a slide down on a COMBO BREAKER, hits and crits on the boss, then a level-clear jingle, an air horn for
  a record, or the sad trombone. Hear them all with `python -m pytest_glow.sound`

![--glow-boss on a green run: the boss gets enraged, makes its last stand and falls, drops loot, and you level up](https://github.com/koskrub-15/pytest-glow/raw/main/docs/demo-boss.gif)

![a green run: combo, a green streak and XP](https://github.com/koskrub-15/pytest-glow/raw/main/docs/demo-green.gif)

![the end of a run up close: a rich traceback, coverage and the verdict](https://github.com/koskrub-15/pytest-glow/raw/main/docs/screenshot.svg)

**Coverage**: with `pytest-cov` installed, its plain table is replaced by a bar per file, the missing line
ranges, per-file gains and drops since the last run, and the total plus `--cov-fail-under` in the verdict.

## Install

```sh
pip install pytest-glow          # or: uv add --dev pytest-glow
```

It's picked up automatically and turns on whenever pytest writes to a terminal. In CI and in pipes,
pytest's standard output stays.

To try it in a project without adding it as a dependency:

```sh
uv run --with pytest-glow pytest
```

## Usage

Just run `pytest`. Everything else is optional:

| | |
|---|---|
| `--no-glow` or `PYTEST_GLOW=0` | use pytest's standard output |
| `--glow` or `PYTEST_GLOW=1` | force it on, even without a terminal (no animation then) |
| `--glow-boss` or `PYTEST_GLOW_BOSS=1` | fight the suite as a boss; `glow_boss = true` in the ini to keep it on |
| `--glow-sound` or `PYTEST_GLOW_SOUND=1` | 8-bit sounds for combos, the boss and the end of the run (terminal only); `glow_sound = true` in the ini |
| `--glow-share[=PATH]` | save the run as an SVG card, `glow-card.svg` by default |
| `--glow-profile` or `PYTEST_GLOW_PROFILE=1` | split test time into the test, your code, libraries and fixtures; `glow_profile = true` in the ini |
| `--glow-watch` | rerun on every save, failures and changed tests first; `f`, `p`, `d`, enter and `q` while it waits |
| `--glow-ff` or `PYTEST_GLOW_FF=1` | run the likely failures first; `glow_ff = true` in the ini |
| `--glow-rerun[=N]` or `PYTEST_GLOW_RERUN=N` | rerun a failed test up to N times (1 by default) and call out flaky ones; `glow_rerun = N` in the ini |
| `PYTEST_GLOW_SUMMARY=0` | no job summary on GitHub Actions; `glow_summary = false` in the ini |
| `PYTEST_GLOW_QUESTS=0` | no daily quests |
| `--glow-wrapped` | show everything glow remembers about the project and exit; with `--glow-share`, save it as SVG |
| `PYTEST_GLOW_LINK` | where clickable paths go, e.g. `pycharm://open?file={path}&line={line}`; `off` to turn them off |
| `-v` | also list every test as it finishes |
| `-q` | only failures and the final summary |
| `--tb=short/line/native` | pytest's own traceback text instead of rich tracebacks; `--tb=no` hides them |

glow steps aside on its own for modes that drive the terminal themselves: `--collect-only`,
`--fixtures`, `--markers`, `--setup-show`/`--setup-plan`, live logging (`log_cli`), `--debug`.

### Coverage

Use pytest-cov as usual:

```sh
pytest --cov=mypkg --cov-report=term-missing --cov-fail-under=90
```

`term`, `term-missing` and `skip-covered` are respected; html, xml and json reports are still written
as configured. Plain `--cov` measures `[tool.coverage.run] source` from your config. Set it there, or
your tests get measured too.

## Compatibility

- Python 3.10+, pytest 8.0+
- Linux and macOS. On Windows glow only runs with an explicit `--glow` (it's untested there).
- Works with pytest-xdist, pytest-cov, `breakpoint()`/`--pdb`, `-x`, `-s`, `--durations`, and plugins that
  add their own terminal summary.
- Under xdist, tracebacks show pytest's highlighted text rather than rich tracebacks, since the exceptions stay
  in the worker processes (assertion diffs come along).
- Not supported yet: `-r` short-summary flags (`-rA`, `-rP`, ...) beyond the failure list.

## Try the demo

The repo has a showcase suite with slow, failing, flaky and skipped tests, warnings and a small package
for coverage:

```sh
uv sync
cd demo
uv run pytest
uv run pytest -n 4
uv run pytest test_shop.py --cov=shop --cov-report=term-missing --cov-fail-under=80
```

Run it a few times: the history features kick in from the second run.

## Development

```sh
uv sync                          # creates .venv with the plugin and dev tools
uv run pytest                    # the plugin's own tests
uv run ruff check src tests && uv run ruff format src tests
```

The tests run pytest in subprocesses (`pytester`) with `--glow` forced and check what comes out.

## License

MIT
