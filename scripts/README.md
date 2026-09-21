# Scripts

These scripts check the source of `canvasapi_async` against conventions
inherited from CanvasAPI. They are not tests: they import the package and
inspect its source, and pytest does not run them.

Run the three convention checks from the repository root:

```
uv run python scripts/find_missing_modules.py
uv run python scripts/alphabetic.py
uv run python scripts/find_missing_kwargs.py
```

Each prints what it found, then exits 1 if it found anything and 0 if it did
not.

## find_missing_modules.py

Every module in `canvasapi_async/` has to be reachable by import from the
package root, directly or through another module. A new module that nothing
imports fails this check.

The other two scripts find classes by asking `inspect` for the modules attached
to the package, so they never look at a module that is never imported. Upstream
added this script after `find_missing_kwargs.py` turned out to be skipping files
(ucfopen/canvasapi issue 459). Run it first. It lists the package directory by
relative path, which is why the scripts have to run from the repository root.

## alphabetic.py

Methods appear in alphabetical order within each class. The output names each
method that sits above one it should follow, with both line numbers.

## find_missing_kwargs.py

Every public method accepts `**kwargs`, so a caller can pass any parameter
Canvas accepts, including ones the library does not name. Upstream added the
rule after a method without `**kwargs` could not be called while masquerading
as another user (ucfopen/canvasapi issue 407).

Methods whose names start with an underscore are skipped. A method with no
reason to forward parameters to Canvas goes in the `WHITELIST` tuple at the top
of the script, by qualified name.

## validate_docstrings.py

This one checks the `:calls:` line in each method docstring against the Canvas
API documentation. The line has to parse as a verb, a path and a documentation
link, and the linked page has to list that verb and path under the linked
heading.

It fetches the documentation pages over the network, prints what it finds, and
always exits 0, so it cannot fail an automated run and is only useful read by
hand. Many of its findings are in modules inherited from upstream, which this
fork leaves as they are. Its parsing is covered by `tests/test_validate_docstrings.py`,
which mocks the documentation pages.
