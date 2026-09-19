import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import anyio
import httpx
import pytest
import requests
import respx
from requests.models import RequestEncodingMixin

from canvasapi_async import async_requester
from canvasapi_async.async_requester import AsyncRequester
from canvasapi_async.exceptions import (
    BadRequest,
    RateLimitExceeded,
    ResourceDoesNotExist,
)
from tests import settings

LOGGER_NAME = "canvasapi_async.async_requester"

# Parameter lists whose form encoding has to survive the move to httpx.
FORM_ENCODING_CASES = [
    pytest.param([("a", "1"), ("b", "2"), ("a", "3")], id="repeated_key_interleaved"),
    pytest.param([("include[]", "submission")], id="bracket_key"),
    pytest.param([("search_term", "art history")], id="value_with_space"),
    pytest.param([("name", "Café Ubuntu")], id="non_ascii_value"),
    pytest.param([("per_page", 2)], id="integer_value"),
    pytest.param([("published", "true")], id="lowercase_boolean_string"),
    pytest.param([("include[]", ["a", "b"])], id="list_value"),
]

# Endpoints and parameter lists whose merged URL has to match what requests
# prepares, including an endpoint that already carries the same key.
QUERY_MERGE_CASES = [
    pytest.param("courses?page=3&per_page=2", [], id="no_parameters"),
    pytest.param("courses?page=3&per_page=2", [("per_page", 2)], id="repeated_key"),
    pytest.param("courses?page=3&per_page=2", [("include[]", "a")], id="added_key"),
    pytest.param("courses", [("per_page", 2)], id="no_query_of_its_own"),
    pytest.param("courses?search=art%20history", [("b", "c d")], id="encoded_query"),
    pytest.param("courses?page=3", [("include[]", ["a", "b"])], id="list_value"),
    pytest.param("courses?", [("a", 1)], id="empty_query"),
    pytest.param("courses#frag", [("a", 1)], id="fragment"),
    pytest.param("courses?page=3#frag", [("a", 1)], id="fragment_after_query"),
    pytest.param("courses?page=3#frag", [], id="no_parameters_with_fragment"),
]

# Methods that carry the parameters in a form body.
FORM_BODY_METHODS = ["POST", "PUT", "PATCH", "DELETE"]

# The content-length each of those methods sends for a form body with no
# parameters at all, paired with the method.
EMPTY_PARAMETER_CASES = [("POST", "0"), ("PUT", "0"), ("PATCH", "0"), ("DELETE", None)]


def make_test_requester(**kwargs: Any) -> AsyncRequester:
    """Build a requester pointed at the fake Canvas instance."""
    return AsyncRequester(settings.BASE_URL, settings.API_KEY, **kwargs)


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_request_get_sends_params_and_auth(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))

    async with make_test_requester() as requester:
        await requester.request_async(
            "GET", "courses", _kwargs=[("include[]", "a"), ("per_page", 2)]
        )

    assert route.call_count == 1
    request = route.calls.last.request
    assert request.url.query == b"include%5B%5D=a&per_page=2"
    assert request.headers["Authorization"] == "Bearer {}".format(settings.API_KEY)


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_request_drops_none_values(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))

    async with make_test_requester() as requester:
        await requester.request_async("GET", "courses", _kwargs=[("a", None), ("b", 1)])

    assert route.calls.last.request.url.query == b"b=1"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_put_drops_none_values(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.put("courses/1").mock(return_value=httpx.Response(200, json={}))

    async with make_test_requester() as requester:
        await requester.request_async(
            "PUT", "courses/1", _kwargs=[("a", None), ("b", 1)]
        )

    assert route.calls.last.request.content == b"b=1"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_get_keeps_the_endpoint_query(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))

    async with make_test_requester() as requester:
        await requester.request_async("GET", "courses?page=3&per_page=2")

    assert route.calls.last.request.url.query == b"page=3&per_page=2"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_get_appends_params_to_the_endpoint_query(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))

    async with make_test_requester() as requester:
        await requester.request_async(
            "GET", "courses?page=3&per_page=2", _kwargs=[("include[]", "a")]
        )

    assert route.calls.last.request.url.query == b"page=3&per_page=2&include%5B%5D=a"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_post_json_keeps_the_endpoint_query(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("graphql").mock(return_value=httpx.Response(200, json={}))

    async with make_test_requester() as requester:
        await requester.request_async(
            "POST", "graphql?page=3", _kwargs=[("a", 1)], json={"q": 1}
        )

    assert route.calls.last.request.url.query == b"page=3&a=1"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_put_keeps_the_endpoint_query_out_of_the_form_body(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.put("courses/1").mock(return_value=httpx.Response(200, json={}))

    async with make_test_requester() as requester:
        await requester.request_async("PUT", "courses/1?page=3", _kwargs=[("a", 1)])

    request = route.calls.last.request
    assert request.url.query == b"page=3"
    assert request.content == b"a=1"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_request_pushes_cache(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))

    async with make_test_requester() as requester:
        response = await requester.request_async("GET", "courses")

        assert requester._cache[0] is response


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_request_400_raises_bad_request(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("400").mock(return_value=httpx.Response(400, text="bad"))

    async with make_test_requester() as requester:
        with pytest.raises(BadRequest) as exc_info:
            await requester.request_async("GET", "400")

    assert exc_info.value.message == "bad"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_request_404_raises_resource_does_not_exist(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("404").mock(return_value=httpx.Response(404, text="gone"))

    async with make_test_requester() as requester:
        with pytest.raises(ResourceDoesNotExist) as exc_info:
            await requester.request_async("GET", "404")

    assert exc_info.value.message == "Not Found"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_concurrency_cap_is_observed(respx_mock: respx.MockRouter) -> None:
    in_flight = 0
    high_water_mark = 0

    async def occupy_the_connection(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, high_water_mark
        in_flight += 1
        high_water_mark = max(high_water_mark, in_flight)
        await anyio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, json=[])

    respx_mock.get("courses").mock(side_effect=occupy_the_connection)

    async with make_test_requester(concurrency=2) as requester:
        await asyncio.gather(
            *(requester.request_async("GET", "courses") for _ in range(10))
        )

    assert high_water_mark == 2


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_quota_floor_pauses_next_request(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(async_requester, "QUOTA_COOLDOWN_SECONDS", 0.05)
    send_times: list[float] = []

    async def report_low_quota(request: httpx.Request) -> httpx.Response:
        send_times.append(time.monotonic())
        return httpx.Response(200, headers={"X-Rate-Limit-Remaining": "10"}, json=[])

    respx_mock.get("courses").mock(side_effect=report_low_quota)

    async with make_test_requester(quota_floor=150) as requester:
        await requester.request_async("GET", "courses")
        await requester.request_async("GET", "courses")

    assert send_times[1] - send_times[0] >= 0.05


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_quota_floor_clears_when_remaining_recovers(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(async_requester, "QUOTA_COOLDOWN_SECONDS", 0.3)
    remaining = iter(["10", "700", "700"])

    async def report_quota(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"X-Rate-Limit-Remaining": next(remaining)}, json=[]
        )

    respx_mock.get("courses").mock(side_effect=report_quota)

    async with make_test_requester(quota_floor=150) as requester:
        await requester.request_async("GET", "courses")
        await requester.request_async("GET", "courses")
        started = time.monotonic()
        await requester.request_async("GET", "courses")
        elapsed = time.monotonic() - started

    assert elapsed < 0.15


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_unparsable_quota_is_logged_and_ignored(
    respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.get("courses").mock(
        return_value=httpx.Response(
            200, headers={"X-Rate-Limit-Remaining": "abc"}, json=[]
        )
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        async with make_test_requester() as requester:
            response = await requester.request_async("GET", "courses")

    assert response.status_code == 200
    messages = [
        record.getMessage() for record in caplog.records if record.name == LOGGER_NAME
    ]
    assert "Ignoring unparsable X-Rate-Limit-Remaining header: abc" in messages


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_429_retries_then_raises(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(async_requester, "BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(async_requester, "BACKOFF_JITTER_SECONDS", 0)
    route = respx_mock.get("throttled").mock(return_value=httpx.Response(429, json={}))

    async with make_test_requester() as requester:
        with pytest.raises(RateLimitExceeded) as exc_info:
            await requester.request_async("GET", "throttled")

    assert exc_info.value.message == (
        "Rate Limit Exceeded. X-Rate-Limit-Remaining: Unknown"
    )
    assert route.call_count == 4


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_429_honours_retry_after(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("throttled").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={}),
            httpx.Response(200, json=[]),
        ]
    )

    async with make_test_requester() as requester:
        response = await requester.request_async("GET", "throttled")

    assert response.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_429_falls_back_to_backoff_when_retry_after_is_not_a_number(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(async_requester, "BACKOFF_BASE_SECONDS", 0.05)
    monkeypatch.setattr(async_requester, "BACKOFF_JITTER_SECONDS", 0)
    respx_mock.get("throttled").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "soon"}, json={}),
            httpx.Response(200, json=[]),
        ]
    )

    async with make_test_requester() as requester:
        started = time.monotonic()
        response = await requester.request_async("GET", "throttled")
        elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed >= 0.05


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_post_json_sends_params_and_body(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("graphql").mock(return_value=httpx.Response(200, json={}))

    async with make_test_requester() as requester:
        await requester.request_async(
            "POST", "graphql", _kwargs=[("a", 1)], json={"q": 1}
        )

    request = route.calls.last.request
    assert request.url.query == b"a=1"
    assert json.loads(request.content) == {"q": 1}


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_put_sends_repeated_keys_as_form_body(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.put("courses/1").mock(return_value=httpx.Response(200, json={}))

    async with make_test_requester() as requester:
        await requester.request_async(
            "PUT", "courses/1", _kwargs=[("name[]", "a"), ("name[]", "b")]
        )

    request = route.calls.last.request
    assert request.content == b"name%5B%5D=a&name%5B%5D=b"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"


@pytest.mark.asyncio
@pytest.mark.parametrize("method, content_length", EMPTY_PARAMETER_CASES)
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_empty_parameters_send_expected_headers(
    respx_mock: respx.MockRouter, method: str, content_length: str | None
) -> None:
    route = respx_mock.route(method=method, url="courses/1").mock(
        return_value=httpx.Response(200, json={})
    )

    async with make_test_requester() as requester:
        await requester.request_async(method, "courses/1")

    request = route.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.headers.get("content-length") == content_length


@pytest.mark.parametrize("method", FORM_BODY_METHODS)
def test_requests_sends_content_length_for_empty_parameters(method: str) -> None:
    """Pin what requests puts on the wire for an empty parameter list."""
    prepared = requests.Request(
        method, settings.BASE_URL_WITH_VERSION + "courses/1", data=[]
    ).prepare()

    assert prepared.headers["Content-Length"] == "0"
    assert "Content-Type" not in prepared.headers


def test_httpx_does_not_form_encode_a_list_of_pairs() -> None:
    """Pin the httpx limit that keeps the form body out of its ``data`` argument."""
    with pytest.warns(DeprecationWarning, match="content="):
        request = httpx.Request(
            "POST",
            settings.BASE_URL_WITH_VERSION + "courses/1",
            data=[("name[]", "a"), ("name[]", "b")],
        )

    assert "content-type" not in request.headers


@pytest.mark.parametrize("params", FORM_ENCODING_CASES)
def test_form_body_encoding_matches_requests(params: list[tuple[str, Any]]) -> None:
    """Pin the claim that lets the form body skip httpx's mapping-only encoder."""
    assert RequestEncodingMixin._encode_params(params) == urlencode(params, doseq=True)


@pytest.mark.asyncio
async def test_httpx_replaces_a_url_query_with_its_parameters() -> None:
    """Pin the httpx behaviour that _merge_query exists to work around."""
    url = settings.BASE_URL_WITH_VERSION + "courses?page=3&per_page=2"

    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", url, params=[("include[]", "a")])

    assert (
        str(request.url) == settings.BASE_URL_WITH_VERSION + "courses?include%5B%5D=a"
    )


@pytest.mark.parametrize("endpoint, params", QUERY_MERGE_CASES)
def test_query_merge_matches_requests(
    endpoint: str, params: list[tuple[str, Any]]
) -> None:
    """Pin the requests URL that _merge_query reproduces."""
    url = settings.BASE_URL_WITH_VERSION + endpoint
    prepared = requests.Request("GET", url, params=params).prepare()

    assert make_test_requester()._merge_query(url, params) == prepared.url


@pytest.mark.asyncio
@respx.mock
async def test_post_file_raises_not_implemented() -> None:
    async with make_test_requester() as requester:
        with pytest.raises(NotImplementedError, match="File uploads"):
            await requester.request_async(
                "POST", "files", _kwargs=[("file", "contents")]
            )


@pytest.mark.asyncio
@respx.mock
async def test_unknown_method_raises_value_error() -> None:
    async with make_test_requester() as requester:
        with pytest.raises(ValueError, match="Unsupported HTTP method: HEAD"):
            await requester.request_async("HEAD", "courses")


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_request_cost_is_logged(
    respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.get("courses").mock(
        return_value=httpx.Response(200, headers={"X-Request-Cost": "0.05"}, json=[])
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        async with make_test_requester() as requester:
            await requester.request_async("GET", "courses")

    messages = [
        record.getMessage() for record in caplog.records if record.name == LOGGER_NAME
    ]
    assert "Request cost: 0.05" in messages


@pytest.mark.asyncio
async def test_aclose_without_request_is_noop() -> None:
    requester = make_test_requester()

    await requester.aclose()

    assert requester._client is None


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_context_manager_closes_client(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))

    async with make_test_requester() as requester:
        await requester.request_async("GET", "courses")
        client = requester._client

    assert client is not None
    assert client.is_closed


def test_sync_request_points_at_the_coroutine() -> None:
    requester = make_test_requester()

    with pytest.raises(NotImplementedError, match="request_async"):
        requester.request("GET", "courses")


def test_governor_settings_are_read_only() -> None:
    requester = make_test_requester()

    assert requester.concurrency == 4
    assert requester.quota_floor == 150
    assert requester.timeout == 60.0
    with pytest.raises(AttributeError):
        requester.concurrency = 8
