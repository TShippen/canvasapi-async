# canvasapi-async

`canvasapi-async` is a fork of
[CanvasAPI](https://github.com/ucfopen/canvasapi), a Python library for accessing
Instructure's [Canvas LMS API](https://canvas.instructure.com/doc/api/index.html).
It reads long paginated lists faster by fetching their pages concurrently.
Everything else works as it does in CanvasAPI 3.6.0, the version the fork
started from.

The fork is at an early stage and its version is below 1.0. The public API can
change between releases. This is a personal project and does not accept
contributions; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## What the fork changes

### Switching from CanvasAPI

Change the import. No other line of a script has to change, and no call needs
`await`.

```python
# Before
from canvasapi import Canvas

# After
from canvasapi_async import Canvas
```

### Concurrent page fetching

Concurrent fetching is on by default. A script does not call anything to turn
it on.

When a script reads a list, such as `user.get_courses()`, the first page is
fetched the way CanvasAPI fetches it. The response shows how Canvas paginates
that endpoint:

- Where Canvas numbers the pages, the pages after the first are fetched several
  at a time, on an event loop that runs on a background thread. The loop starts
  the first time it is needed.
- Where Canvas paginates with a bookmark cursor, as the enrollment endpoints
  do, each page names the next one, so the pages are fetched one at a time.

A list that fits on one page costs one request and starts no background
thread.

The concurrent fetches pause for a cooldown when Canvas reports that the rate
limit quota is running low. They also retry a request that Canvas throttles.

### Changing the limits

The concurrent fetches run under three limits. Their defaults are in the
signature of `AsyncRequester` in `canvasapi_async/async_requester.py`, and
`configure()` changes them:

- `concurrency`: how many requests run at once. A whole number of at least 1.
- `quota_floor`: the remaining rate limit quota, as Canvas reports it in the
  `X-Rate-Limit-Remaining` header, below which the fetches pause. A whole
  number of at least 0.
- `timeout`: how many seconds one request may take. A number above 0.

```python
from canvasapi_async import configure

configure(concurrency=8, quota_floor=200, timeout=30)
```

Call it before fetching anything. It raises `RuntimeError` once the background
loop has started, `TypeError` for a value of the wrong type, and `ValueError`
for a value out of range. A refused call changes no setting.

`shutdown()` closes the connections and stops the background loop. It runs at
interpreter exit, where it waits for a request still in flight, and you can call
it earlier. After it returns, `configure()` accepts new settings, and the next
concurrent fetch starts a fresh loop.

### What stays synchronous

The limits apply only to the concurrent fetches. The first page of every list,
every page of a bookmark-paginated list, and every other call in the library go
through the same synchronous `requests` session CanvasAPI uses. That session
runs one request at a time, does not pause on the rate limit quota, and waits
for a response indefinitely.

### Differences to expect

- An HTTP error status raises the same exception classes as CanvasAPI on every
  path. A connection failure or a timeout raises an `httpx` exception on a
  concurrently fetched page and a `requests` exception everywhere else.
- When Canvas does not report how many pages a list has, the last batch asks
  for pages past the end. Those come back empty.
- Open-ended slices such as `courses[2:]` work. In CanvasAPI 3.6.0 they raise
  `TypeError`.

## Installation

The package is not on PyPI. Install it from the repository:

```
pip install git+https://github.com/TShippen/canvasapi-async.git
```

This installs the `main` branch, which moves only when a version is ready.
Development happens on `develop`. To install its latest commit, append
`@develop` to the URL; to install a fixed point, append `@` and a commit hash.
pip does not replace an installed copy whose version string has not changed,
so to update an install from `develop`, add `--force-reinstall`. Python 3.10
or later is required.

## Using the library

The classes and methods are those of CanvasAPI 3.6.0. A `Canvas` object gives
access to the rest of the API, and the objects it returns have methods of
their own:

```python
from canvasapi_async import Canvas

canvas = Canvas("https://example.com", "your-api-key")

user = canvas.get_user(123)
print(user.name)

# Keyword arguments are sent to Canvas as request parameters.
courses = user.get_courses(enrollment_state="active")

for course in courses:
    print(course)
```

A call that returns many objects returns a `PaginatedList`. You can iterate
over it, index it, and slice it. It loads its records as they are asked for, so
it does not know its own length, and negative indexes are not supported. It
sends `per_page=100` unless you pass your own `per_page`.

For the rest of the API, see
[CanvasAPI](https://github.com/ucfopen/canvasapi). The Sphinx documentation
under `docs/` is a frozen copy that describes CanvasAPI 3.6.0 under its
original import name; [`docs/FROZEN.md`](docs/FROZEN.md) explains its status.

## Development

The project uses [uv](https://docs.astral.sh/uv/). Install the environment once,
then run any check on its own:

```
uv sync
uv run pytest
uv run coverage run -m pytest
uv run coverage report
uv run ruff check canvasapi_async tests
uv run ruff format --check canvasapi_async tests
uv run mypy
```

`coverage report` fails when coverage falls below the threshold set in
`pyproject.toml`. Three scripts check source conventions that ruff has no rule
for; [`scripts/README.md`](scripts/README.md) explains them.

Every push runs all of these on GitHub, on each supported Python version,
through [`.github/workflows/checks.yml`](.github/workflows/checks.yml). The
results are a report. They do not block a push or a merge.

## Project goals

- **Full static typing.** Annotations are added one module at a time, and mypy
  checks the annotated modules listed in `pyproject.toml`. When a module is
  annotated, its docstrings drop the `:type:` and `:rtype:` fields, so the
  signature is the single source for types.
- **Staying mergeable with upstream.** The resource modules take only the
  changes upstream CanvasAPI has merged or will merge, so that future upstream
  releases can be merged here. New behaviour lives in the request, pagination,
  and base object layers.

## Attribution

This project is a fork of [CanvasAPI](https://github.com/ucfopen/canvasapi) by the
University of Central Florida - Center for Distributed Learning, originally
licensed under the MIT License. It remains under the MIT License. See
[`NOTICE`](NOTICE) and [`LICENSE`](LICENSE) for details, and
[`AUTHORS.md`](AUTHORS.md) for the upstream contributors whose work this builds on.

## License

MIT. See [`LICENSE`](LICENSE).
