import json
import os
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import requests_mock

from tests import settings

# Every fixture the running test registered, as
# (method, url, status_code, headers, data), in the order it registered them.
# The conftest fixture clears it around each test.
HTTPX_FIXTURES: list[tuple[Any, Any, int, dict[str, str], Any]] = []

# The respx route the conftest fixture answers httpx requests through. A test
# reads its calls, and may replace its side effect to watch or delay them.
HTTPX_ROUTE: Any = None


def httpx_fixture_response(request: httpx.Request) -> httpx.Response:
    """
    Answer an httpx request from the fixtures the running test registered.

    The last matching fixture wins. A fixture registered without a page number
    answers only a request that asks for none: a page-one fixture that
    answered every page would hand back page one's records and page one's next
    link forever, and nothing would ever find the end of the list.

    Anything unmatched is answered with an empty page, which is what Canvas
    returns past the end of a list.

    :param request: The request to answer.
    """
    for method, url, status_code, headers, data in reversed(HTTPX_FIXTURES):
        if method is not requests_mock.ANY and method != request.method:
            continue
        if url is not requests_mock.ANY and not _answers(url, request):
            continue

        return httpx.Response(status_code, headers=headers, json=data)

    return httpx.Response(200, json=[])


def _answers(url, request: httpx.Request) -> bool:
    """
    Whether a fixture's URL answers a request's, path and page number alike.

    A page number absent from both counts as the same page.

    :param url: The URL the fixture was registered under.
    :param request: The request to answer.
    """
    registered = urlparse(url)
    page = parse_qs(registered.query).get("page", [None])[0]

    return registered.path == request.url.path and page == request.url.params.get(
        "page"
    )


def register_uris(requirements, requests_mocker, base_url=None):
    """
    Given a list of required fixtures and an requests_mocker object,
    register each fixture as a uri with the mocker.

    :param base_url: str
    :param requirements: dict
    :param requests_mocker: requests_mock.mocker.Mocker
    """
    if base_url is None:
        base_url = settings.BASE_URL_WITH_VERSION
    for fixture, objects in requirements.items():
        try:
            with open("tests/fixtures/{}.json".format(fixture)) as file:
                data = json.loads(file.read())
        except (IOError, ValueError):
            raise ValueError("Fixture {}.json contains invalid JSON.".format(fixture))

        if not isinstance(objects, list):
            raise TypeError("{} is not a list.".format(objects))

        for obj_name in objects:
            obj = data.get(obj_name)

            if obj is None:
                raise ValueError(
                    "{} does not exist in {}.json".format(obj_name.__repr__(), fixture)
                )

            method = requests_mock.ANY if obj["method"] == "ANY" else obj["method"]
            if obj["endpoint"] == "ANY":
                url = requests_mock.ANY
            else:
                url = base_url + obj["endpoint"]

            status_code = obj.get("status_code", 200)
            headers = obj.get("headers", {})

            # The same fixture is registered with both mockers, so a list that
            # pages concurrently over httpx answers from the entries its test
            # named, exactly as the synchronous path does.
            HTTPX_FIXTURES.append((method, url, status_code, headers, obj.get("data")))

            try:
                requests_mocker.register_uri(
                    method,
                    url,
                    json=obj.get("data"),
                    status_code=status_code,
                    headers=headers,
                )
            except Exception as e:
                print(e)


def cleanup_file(filename):
    """
    Remove a test file from the system. If the file doesn't exist, ignore.

    `Not as stupid as it looks. <http://stackoverflow.com/a/10840586>_`
    """
    try:
        os.remove(filename)
    except OSError:
        pass
