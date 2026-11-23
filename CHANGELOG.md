# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

- `--glow-profile`: where a test's time goes, the test itself, your code, libraries or fixtures, by sampling
  its stack; per slow test and for the whole run, with the libraries that take the most.
- Assertion diffs under xdist too, and for `in`: the near misses when it isn't there, where it is for `not in`.
- Tips, when something takes a good part of the run: a fixture worth a wider scope, and with `--glow-profile`
  libraries slow on purpose (argon2, bcrypt…) and tests that sleep; with what to do about it.
- `--glow-profile` keeps its numbers out of junitxml, and counts conftest fixtures as your code.
- The ghost of your personal best races the run, under the progress bar: ahead of it, or behind.
- Fixed: the green streak stopped at 31.
- Fixed: "faster than last run" compared with an older run of as many tests while saying "last run".

## [0.5.0] - 2026-11-21

- Under each failure, what its history says: red for how many runs, the same failure or a new one, and when
  and at which commit it last passed.
- Watch mode keys: `f` only failed, `p` a `-k` pattern, `d` the failures in pdb, enter all, `q` quit.
- Daily quests: three small goals a day, with progress in the verdict and XP when done.

## [0.4.0] - 2026-11-20

- `pytest --glow-watch`: reruns on every save, failures and the tests you changed first.
- `--glow-ff`: runs first what failed last time, the tests you're editing, new and flaky tests.
- `--glow-rerun[=N]`: reruns failed tests; ones that then pass are called out as flaky.
- On GitHub Actions, a job summary of the run: failures with links to the line, flaky and slowest tests.

## [0.3.0] - 2026-11-19

- Failures that failed the same way are grouped under one traceback.
- Clickable paths for tests, files and failures (OSC 8); `PYTEST_GLOW_LINK` picks the URL.
- A test running for over 3s shows the line it's stuck on and what it's waiting in.
- The slowest fixtures, with setup and teardown time.
- XP and levels with titles; a level up gets confetti and a jingle.
- Shiny runs: one green run in 500 comes out gold, with the Shiny Hunter achievement.
- Boss phases (ENRAGED, LAST STAND, with a roar) and loot from slain bosses.
- `pytest --glow-wrapped`: everything glow remembers about the project, as a recap.

## [0.2.0] - 2026-11-19

- Truecolor gradients throughout; the live bar shimmers and freshly finished tests flash in the file strips.
- The verdict sweeps in on a terminal; confetti for a new personal best or an achievement.
- Personal bests per number of tests, and fourteen achievements unlocked once per project.
- `--glow-boss`: the run as a boss fight against the project's nemesis.
- `--glow-share` saves the run as an SVG card.
- `--glow-sound`: synthesized 8-bit sounds for combo milestones, combo breakers, boss hits and the end of the run.
- Under xdist, a live line per worker with the test it's running.
- Live combo counter for passes in a row, and the max combo in the verdict.
- A ready-to-paste command to rerun the failures.
- Tests that got at least twice as slow as usual are called out.
- On a red run: what changed in git since the last green run, or a hint when nothing did.
- `git blame` for the failing line under each failure.
- Duration sparklines in the slowest list.
- Easter eggs for 67 and 69 passed tests.
- Diffs for failed `==` assertions (dicts, lists, sets, strings, numbers, dataclasses, namedtuples), and
  failure one-liners that name the first difference.
- Fix: the counts in the verdict were drawn dimmed.

## [0.1.0]

First release.

- Live view: a progress line per running file, a timer on slow tests, an overall bar with ETA.
- Failures reported the moment they happen; rich tracebacks with locals and captured output at the end.
- Respects `--tb`, `-v`, `-q`, `-x`, `-s`, `breakpoint()`/`--pdb`, `--durations` and other plugins' terminal summaries.
- pytest-xdist support.
- pytest-cov support: per-file bars, missing lines, total and `--cov-fail-under` in the verdict.
- History in `.pytest_cache`: green streaks, fixed/newly failing tests, flaky tests, timing and coverage deltas.
- `--glow` / `--no-glow` and `PYTEST_GLOW=0|1`.
