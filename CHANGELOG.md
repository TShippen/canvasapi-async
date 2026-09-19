# Change Log

This changelog covers `canvasapi-async`, an async-focused fork of
[CanvasAPI](https://github.com/ucfopen/canvasapi). The change history of the
upstream project, up to the point of the fork (version 3.6.0), is preserved in
[CHANGELOG.upstream.md](CHANGELOG.upstream.md).

## [Unreleased]

### New Features

- `PaginatedList` now fetches the pages after the first concurrently on
  endpoints that paginate by page number. It asks for a batch of pages at a
  time, and the batch grows as a read goes on. An endpoint that paginates by
  bookmark cursor is still followed one page at a time, and a list that fits on
  one page still costs one request.
- Open-ended slices such as `courses[2:]` now work. They previously raised
  `TypeError`.
- Added `configure()` and `shutdown()` to the package root. `configure()` sets
  the number of requests in flight at once (`concurrency`), the rate limit
  quota below which requests pause (`quota_floor`), and the number of seconds a
  single request may take (`timeout`); call it before fetching anything,
  because it raises `RuntimeError` once the background event loop has started.
  `shutdown()` closes the connections and stops the background event loop. It
  runs at interpreter exit and can be called earlier.
- Added `httpx` and `anyio` as dependencies. On an endpoint that paginates by
  page number, a transport error on a page after the first is an `httpx`
  exception rather than a `requests` one. An endpoint that paginates by
  bookmark cursor is still fetched through `requests` and still raises its
  errors.
- Reading a list all the way through costs a few extra requests when Canvas
  does not report how long the list is. The last batch asks for pages past the
  end of the list, and those come back empty.

### Bugfixes

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

### General

- Forked from CanvasAPI 3.6.0 by the University of Central Florida - Center for
  Distributed Learning.
- Renamed the package to `canvasapi-async` (import name `canvasapi_async`).
- Reset versioning to `0.1.0` as a new project lineage.

### Backstage

- Migrated packaging to `uv` and `pyproject.toml` (hatchling build backend).
- Replaced `black`, `isort`, and `flake8` with `ruff` for linting and formatting.
- Removed GitHub Actions CI workflows.
- Froze the Sphinx documentation and removed the Read the Docs and GitHub Pages
  build configurations.
- Added fork attribution (`NOTICE`, updated `LICENSE` and `AUTHORS.md`).
