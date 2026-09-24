# Change Log

This changelog covers `canvasapi-async`, an async-focused fork of
[CanvasAPI](https://github.com/ucfopen/canvasapi). The change history of the
upstream project, up to the point of the fork (version 3.6.0), is preserved in
[CHANGELOG.upstream.md](CHANGELOG.upstream.md).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `PaginatedList` now fetches the pages after the first concurrently on
  endpoints that paginate by page number. It asks for a batch of pages at a
  time, and the batch grows as a read goes on. An endpoint that paginates by
  bookmark cursor is still followed one page at a time, and a list that fits on
  one page still costs one request.
- Open-ended slices such as `courses[2:]` now work. They previously raised
  `TypeError`.
- `configure()` and `shutdown()` at the package root. `configure()` sets
  the number of requests in flight at once (`concurrency`), the rate limit
  quota below which requests pause (`quota_floor`), and the number of seconds a
  single request may take (`timeout`); call it before fetching anything,
  because it raises `RuntimeError` once the background event loop has started.
  It raises `TypeError` for a value of the wrong type and `ValueError` for a
  `concurrency` below 1, a `quota_floor` below 0, or a `timeout` of 0 or less.
  `shutdown()` closes the connections and stops the background event loop. It
  runs at interpreter exit and can be called earlier.
- `httpx` and `anyio` as dependencies. On an endpoint that paginates by
  page number, a transport error on a page after the first is an `httpx`
  exception rather than a `requests` one. An endpoint that paginates by
  bookmark cursor is still fetched through `requests` and still raises its
  errors.
- A coverage threshold of 100% in `pyproject.toml`. `coverage report` now
  fails when coverage drops below it.
- A GitHub Actions workflow that runs the tests, coverage, ruff, mypy, and the
  source convention scripts on every push, on each supported Python version.
  The results are a report. No rule makes them required, so a failure does not
  block a push or a merge.
- A `CONTRIBUTING.md` stating that contributions are not accepted.
- The minimum uv version, declared in `pyproject.toml`.

### Changed

- Reading a list all the way through costs a few extra requests when Canvas
  does not report how long the list is. The last batch asks for pages past the
  end of the list, and those come back empty.
- The version is `0.2.0.dev0` while the next release is in development.
- pytest is the test runner, with a timeout of sixty seconds per test.
- ruff's flake8-async rules are enabled. They flag blocking calls inside async
  functions.

### Removed

- `scripts/run_tests.sh`. The README's Development section lists the
  commands, and `scripts/README.md` describes the convention scripts.
- The issue and pull request templates inherited from upstream.
- The deploy document and the markdown lint configuration inherited from
  upstream, and unused entries from `.gitignore`.

### Fixed

- Fixed an issue where kwargs were not passed along to Canvas at nineteen
  `PaginatedList` and `request` call sites across the resource modules
  (issue #685, PR #686. Thanks, [@superle3](https://github.com/superle3)).
- Fixed the same issue at `Blueprint.show_blueprint_migration`, which was
  not part of upstream PR #686.
- Fixed `PaginatedList` overriding a caller's `per_page`, which sent the
  parameter twice on the first request. `PaginatedList` now accepts `_kwargs`
  and only defaults `per_page` to 100 when the caller supplied no value
  (issue #685, PR #686. Thanks, [@superle3](https://github.com/superle3)). The
  PR's `docs/getting-started.rst` change was not applied, because the local
  Sphinx tree is frozen.

## [0.1.0]

Initial release of the fork. This establishes a clean, modernized foundation;
the asynchronous rewrite is tracked separately.

### Added

- Fork attribution (`NOTICE`, updated `LICENSE` and `AUTHORS.md`).

### Changed

- Forked from CanvasAPI 3.6.0 by the University of Central Florida - Center for
  Distributed Learning.
- Renamed the package to `canvasapi-async` (import name `canvasapi_async`).
- Reset versioning to `0.1.0` as a new project lineage.
- Migrated packaging to `uv` and `pyproject.toml` (hatchling build backend).
- Replaced `black`, `isort`, and `flake8` with `ruff` for linting and formatting.
- Froze the Sphinx documentation.

### Removed

- GitHub Actions CI workflows.
- The Read the Docs and GitHub Pages build configurations.
