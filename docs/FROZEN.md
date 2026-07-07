# Frozen documentation

The Sphinx documentation in this `docs/` directory is **frozen and unmaintained**.

It describes the **synchronous** API of the upstream
[CanvasAPI](https://github.com/ucfopen/canvasapi) project (up to version 3.6.0),
from which `canvasapi-async` was forked. It is kept in the repository as a
historical reference only.

What this means:

- These docs are **not built or published**. The Read the Docs and GitHub Pages
  configurations have been removed, and no CI builds them.
- They may not match the current `canvasapi_async` package (for example, the
  package/import rename and any later async changes are not reflected here).
- `docs/conf.py` still references the old import name and is intentionally left
  untouched; because the docs are no longer built, this does not matter.

This freeze does **not** apply to `docs/superpowers/`, which holds active
planning and design specs for this fork.

Documentation will be revisited after the async rewrite.
