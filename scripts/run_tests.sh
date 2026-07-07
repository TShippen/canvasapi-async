#!/bin/sh

coverage run -m unittest discover
coverage report
coverage html
black --check canvasapi_async tests
isort --check canvasapi_async tests
flake8 canvasapi_async tests
mdl . .github
python scripts/find_missing_modules.py
python scripts/alphabetic.py
python scripts/find_missing_kwargs.py
