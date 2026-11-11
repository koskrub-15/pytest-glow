# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

First release.

- Live view: a progress line per running file, a timer on slow tests, an overall bar with ETA.
- Failures reported the moment they happen; rich tracebacks with locals and captured output at the end.
- Respects `--tb`, `-v`, `-q`, `-x`, `-s`, `breakpoint()`/`--pdb`, `--durations` and other plugins' terminal summaries.
- pytest-xdist support.
- pytest-cov support: per-file bars, missing lines, total and `--cov-fail-under` in the verdict.
- History in `.pytest_cache`: green streaks, fixed/newly failing tests, flaky tests, timing and coverage deltas.
- `--glow` / `--no-glow` and `PYTEST_GLOW=0|1`.
