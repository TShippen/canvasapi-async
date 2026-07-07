# Change Log

This changelog covers `canvasapi-async`, an async-focused fork of
[CanvasAPI](https://github.com/ucfopen/canvasapi). The change history of the
upstream project, up to the point of the fork (version 3.6.0), is preserved in
[CHANGELOG.upstream.md](CHANGELOG.upstream.md).

## [Unreleased]

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
