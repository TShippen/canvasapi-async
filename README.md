# canvasapi-async

`canvasapi-async` is a fork of
[CanvasAPI](https://github.com/ucfopen/canvasapi), a Python library for accessing
Instructure's [Canvas LMS API](https://canvas.instructure.com/doc/api/index.html).
It reads long paginated lists faster by fetching pages concurrently, and it
pauses those fetches when the Canvas rate limit quota runs low. Everything else
works as it does in CanvasAPI. The classes and methods are the same, and every
call is still synchronous. A script switches to this fork by changing its
import from `canvasapi` to `canvasapi_async`.

The fork is at an early stage and its version is below 1.0. The public API can
change between releases. This is a personal project and does not accept
contributions; see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Goals

- **Faster reads of paginated lists.** Where Canvas numbers the pages of a list,
  the pages after the first are fetched concurrently. The synchronous object API
  stays as it is.
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

## Installation

The package is not on PyPI. Install it from the repository:

```
pip install git+https://github.com/TShippen/canvasapi-async.git
```

This installs the latest commit on the `develop` branch. To install a fixed
point instead, append `@` and a commit hash or tag to the URL. Python 3.10 or
later is required.

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

## Documentation

The upstream Sphinx documentation is retained under `docs/` for reference but is
**frozen and unmaintained** (see [`docs/FROZEN.md`](docs/FROZEN.md)). It describes
the synchronous API and does not reflect the fork's rename or async changes.

## Quickstart

Like the upstream library, `canvasapi-async` exposes a `Canvas` class that
provides access to the rest of the API. The package also exports `configure()`
and `shutdown()`, described under Paginated Lists below.

Instantiate a `Canvas` object with your Canvas instance's root API URL and a valid
API key:

```python
# Import the Canvas class
from canvasapi_async import Canvas

# Canvas API URL
API_URL = "https://example.com"
# Canvas API key
API_KEY = "p@$$w0rd"

# Initialize a new Canvas object
canvas = Canvas(API_URL, API_KEY)
```

You can now use `canvas` to begin making API calls.

### Working with Canvas Objects

`canvasapi-async` converts the JSON responses from the Canvas API into Python
objects. These objects provide further access to the Canvas API.

#### Course objects

Courses can be retrieved from the API:

```python
# Grab course 123456
>>> course = canvas.get_course(123456)

# Access the course's name
>>> course.name
'Test Course'

# Update the course's name
>>> course.update(course={'name': 'New Course Name'})
```

#### User objects

Individual users can be pulled from the API as well:

```python
# Grab user 123
>>> user = canvas.get_user(123)

# Access the user's name
>>> user.name
'Test User'

# Retrieve a list of courses the user is enrolled in
>>> courses = user.get_courses()

# Grab a different user by their SIS ID
>>> login_id_user = canvas.get_user('some_user', 'sis_login_id')
```

#### Paginated Lists

Some calls, like the `user.get_courses()` call above, will request multiple
objects from Canvas's API. `canvasapi-async` collects these objects in a
`PaginatedList` object. `PaginatedList` generally acts like a regular Python list.
You can grab an element by index, iterate over it, and take a slice of it.

**Warning**: `PaginatedList` lazily loads its elements. There's no way to determine
the exact number of records Canvas will return without traversing the list fully.
This means that `PaginatedList` isn't aware of its own length and negative indexing
is not supported. Slices with a start and a stop work, and so do open-ended
slices such as `courses[2:]`.

```python
# Retrieve a list of courses the user is enrolled in
>>> courses = user.get_courses()

>>> print(courses)
<PaginatedList of type Course>

# Iterate over our course list
>>> for course in courses:
         print(course)

TST101 Test Course 1 (1234567)
TST102 Test Course 2 (1234568)
TST103 Test Course 3 (1234569)
```

Every `PaginatedList` fetches its first page synchronously, the way CanvasAPI
does. What happens next depends on how Canvas paginates the endpoint. Where
Canvas numbers the pages, `canvasapi-async` fetches the pages after the first
concurrently, on an event loop that runs on a background thread and starts at
the first such fetch. Where Canvas paginates with a bookmark cursor, as the
enrollment endpoints do, the pages are still fetched one at a time.

`configure()` sets three limits on the concurrent fetches:

- `concurrency`: how many requests run at once. A whole number of at least 1.
- `quota_floor`: the remaining rate limit quota, as Canvas reports it in the
  `X-Rate-Limit-Remaining` header, below which the fetches pause for a
  cooldown. A whole number of at least 0.
- `timeout`: how many seconds one request may take. A number above 0.

```python
>>> from canvasapi_async import configure

>>> configure(concurrency=8, quota_floor=200, timeout=30)
```

Call it before fetching anything. It raises `RuntimeError` once the background
loop has started, `TypeError` for a value of the wrong type, and `ValueError`
for a value out of range. A refused call changes no setting.

These limits apply only to the concurrent fetches. The first page of every
list, every page of a bookmark-paginated list, and every other call in the
library go through the synchronous `requests` session. That session runs one
request at a time, does not pause on the rate limit quota, and waits for a
response indefinitely.

`shutdown()` closes the connections and stops the background loop. It runs at
interpreter exit, where it waits for a request still in flight, and you can call
it earlier. After it returns, `configure()` accepts new settings, and the next
concurrent fetch starts a fresh loop.

#### Keyword arguments

Most of Canvas's API endpoints accept a variety of arguments. `canvasapi-async`
allows developers to insert keyword arguments when making calls to endpoints that
accept arguments.

```python
# Get all of the active courses a user is currently enrolled in
>>> courses = user.get_courses(enrollment_state='active')
```

A call that returns a `PaginatedList` sends `per_page=100` unless you pass your
own `per_page`.

## License

MIT. See [`LICENSE`](LICENSE).
