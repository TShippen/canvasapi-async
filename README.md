# canvasapi-async

`canvasapi-async` is an async-focused fork of
[CanvasAPI](https://github.com/ucfopen/canvasapi), a Python library for accessing
Instructure's [Canvas LMS API](https://canvas.instructure.com/doc/api/index.html).
The goal of this fork is to pull records in batches more quickly while respecting
Canvas API rate limits.

> **Note:** This is an early-stage fork (version 0.1.0). The current codebase is
> the modernized synchronous foundation inherited from CanvasAPI 3.6.0; the
> asynchronous rewrite is in progress.

## Attribution

This project is a fork of [CanvasAPI](https://github.com/ucfopen/canvasapi) by the
University of Central Florida - Center for Distributed Learning, originally
licensed under the MIT License. It remains under the MIT License. See
[`NOTICE`](NOTICE) and [`LICENSE`](LICENSE) for details, and
[`AUTHORS.md`](AUTHORS.md) for the upstream contributors whose work this builds on.

## Installation

Install directly from the repository:

```
pip install git+https://github.com/TShippen/canvasapi-async.git
```

For local development (using [uv](https://docs.astral.sh/uv/)):

```
uv sync
uv run python -m unittest discover -s tests
```

## Documentation

The upstream Sphinx documentation is retained under `docs/` for reference but is
**frozen and unmaintained** (see [`docs/FROZEN.md`](docs/FROZEN.md)). It describes
the synchronous API and does not reflect the fork's rename or async changes.

## Quickstart

Like the upstream library, `canvasapi-async` exposes a single `Canvas` class that
provides access to the rest of the API.

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
is not currently supported.

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

#### Keyword arguments

Most of Canvas's API endpoints accept a variety of arguments. `canvasapi-async`
allows developers to insert keyword arguments when making calls to endpoints that
accept arguments.

```python
# Get all of the active courses a user is currently enrolled in
>>> courses = user.get_courses(enrollment_state='active')
```

## License

MIT. See [`LICENSE`](LICENSE).
