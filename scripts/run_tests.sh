#!/bin/sh

coverage run -m unittest discover
coverage report
coverage html
ruff check canvasapi_async tests
ruff format --check canvasapi_async tests
mdl . .github
python scripts/find_missing_modules.py
python scripts/alphabetic.py
python scripts/find_missing_kwargs.py
