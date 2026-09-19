import time
from typing import Any

import anyio
import httpx
import pytest
import requests
import respx

from canvasapi_async.async_requester import AsyncRequester
from canvasapi_async.concurrent_pagination import fetch_pages, page_number, page_url
from canvasapi_async.exceptions import Forbidden
from canvasapi_async.paginated_list import PaginatedList
from canvasapi_async.user import User
from tests import settings

# The list every test paginates, as a stripped path with a query, which is the
# shape PaginatedList holds a next URL in.
TEMPLATE = "courses?page=1&per_page=2"


def make_test_requester(**kwargs: Any) -> AsyncRequester:
    """Build a requester pointed at the fake Canvas instance."""
    return AsyncRequester(settings.BASE_URL, settings.API_KEY, **kwargs)


def make_test_list(requester: AsyncRequester, **kwargs: Any) -> PaginatedList[User]:
    """Build a list over the routed courses endpoint."""
    return PaginatedList(User, requester, "GET", "courses", per_page=2, **kwargs)


def register_pages(
    respx_mock: respx.MockRouter,
    page_count: int,
    *,
    per_page: int = 2,
    root: str | None = None,
) -> respx.Route:
    """
    Route a list of ``page_count`` pages, answering anything past its end with
    no records at all.
    """

    def link(number: int, rel: str) -> str:
        url = "{}courses?page={}&per_page={}".format(
            settings.BASE_URL_WITH_VERSION, number, per_page
        )
        return '<{}>; rel="{}"'.format(url, rel)

    async def respond(request: httpx.Request) -> httpx.Response:
        number = int(request.url.params["page"])

        if number > page_count:
            empty: Any = {root: []} if root else []
            return httpx.Response(200, json=empty)

        first = (number - 1) * per_page + 1
        records = [{"id": identifier} for identifier in range(first, first + per_page)]
        headers = {"Link": link(number + 1, "next")} if number < page_count else {}
        body: Any = {root: records} if root else records

        return httpx.Response(200, headers=headers, json=body)

    return respx_mock.get("courses").mock(side_effect=respond)


def test_page_number_integer() -> None:
    assert page_number("courses?page=3&per_page=2") == 3


def test_page_number_bookmark() -> None:
    assert page_number("x?page=bookmark:abc") is None


def test_page_number_absent() -> None:
    assert page_number("x?per_page=2") is None


def test_page_url_replaces_page() -> None:
    assert page_url("x?page=2&per_page=2", 7) == "x?page=7&per_page=2"


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_returns_pages_in_order(
    respx_mock: respx.MockRouter,
) -> None:
    register_pages(respx_mock, 4)

    async with make_test_requester() as requester:
        pages = await fetch_pages(
            requester, make_test_list(requester), TEMPLATE, [3, 2]
        )

    assert list(pages) == [2, 3]
    assert [record.id for record in pages[2].records] == [3, 4]
    assert [record.id for record in pages[3].records] == [5, 6]


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_reads_the_page_a_response_says_it_is(
    respx_mock: respx.MockRouter,
) -> None:
    link = '<{}courses?page=5&per_page=2>; rel="current"'.format(
        settings.BASE_URL_WITH_VERSION
    )
    respx_mock.get("courses").mock(
        return_value=httpx.Response(200, headers={"Link": link}, json=[{"id": 1}])
    )

    async with make_test_requester() as requester:
        pages = await fetch_pages(requester, make_test_list(requester), TEMPLATE, [2])

    assert pages[2].current == 5


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_past_end_has_no_records(
    respx_mock: respx.MockRouter,
) -> None:
    register_pages(respx_mock, 4)

    async with make_test_requester() as requester:
        pages = await fetch_pages(requester, make_test_list(requester), TEMPLATE, [9])

    assert pages[9].records == []


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_empty_root_body_has_no_records(
    respx_mock: respx.MockRouter,
) -> None:
    register_pages(respx_mock, 4, root="items")

    async with make_test_requester() as requester:
        plist = make_test_list(requester, _root="items")
        pages = await fetch_pages(requester, plist, TEMPLATE, [9])

    assert pages[9].records == []


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_missing_root_raises_value_error(
    respx_mock: respx.MockRouter,
) -> None:
    register_pages(respx_mock, 4, root="items")

    async with make_test_requester() as requester:
        plist = make_test_list(requester, _root="wrong")
        with pytest.raises(ValueError, match="wrong"):
            await fetch_pages(requester, plist, TEMPLATE, [2])


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_raises_the_canvas_exception(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("courses", params={"page": "2"}).mock(
        return_value=httpx.Response(403, text="no")
    )
    register_pages(respx_mock, 4)

    async with make_test_requester() as requester:
        with pytest.raises(Forbidden):
            await fetch_pages(requester, make_test_list(requester), TEMPLATE, [2, 3])


@pytest.mark.asyncio
# The cancelled requests never finish, so respx never records them as calls.
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION, assert_all_called=False)
async def test_fetch_pages_cancels_siblings_on_a_failure(
    respx_mock: respx.MockRouter,
) -> None:
    in_flight: list[int] = []
    answered: list[int] = []

    async def fail_once_the_others_are_in_flight(
        request: httpx.Request,
    ) -> httpx.Response:
        await anyio.sleep(0.05)
        return httpx.Response(403, text="no")

    async def answer_slowly(request: httpx.Request) -> httpx.Response:
        in_flight.append(int(request.url.params["page"]))
        await anyio.sleep(5)
        answered.append(int(request.url.params["page"]))
        return httpx.Response(200, json=[])

    respx_mock.get("courses", params={"page": "2"}).mock(
        side_effect=fail_once_the_others_are_in_flight
    )
    respx_mock.get("courses").mock(side_effect=answer_slowly)

    started = time.monotonic()
    async with make_test_requester(concurrency=4) as requester:
        with pytest.raises(Forbidden):
            await fetch_pages(
                requester, make_test_list(requester), TEMPLATE, [2, 3, 4, 5]
            )
    elapsed = time.monotonic() - started

    assert sorted(in_flight) == [3, 4, 5]
    assert answered == []
    assert respx_mock.calls.call_count == 1
    assert elapsed < 2


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION, assert_all_called=False)
async def test_fetch_pages_stops_when_an_outer_scope_cancels(
    respx_mock: respx.MockRouter,
) -> None:
    async def answer_slowly(request: httpx.Request) -> httpx.Response:
        await anyio.sleep(5)
        return httpx.Response(200, json=[])

    respx_mock.get("courses").mock(side_effect=answer_slowly)
    pages = None

    started = time.monotonic()
    async with make_test_requester() as requester:
        with anyio.move_on_after(0.1) as scope:
            pages = await fetch_pages(
                requester, make_test_list(requester), TEMPLATE, [2, 3]
            )
    elapsed = time.monotonic() - started

    assert scope.cancelled_caught
    assert pages is None
    assert elapsed < 2


@pytest.mark.asyncio
async def test_cancelled_exception_is_not_an_exception() -> None:
    """Pin the anyio fact that keeps a cancelled page task out of the failures."""
    assert not issubclass(anyio.get_cancelled_exc_class(), Exception)


@pytest.mark.asyncio
@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
async def test_fetch_pages_records_parity_with_root_and_extra_attribs(
    respx_mock: respx.MockRouter,
) -> None:
    register_pages(respx_mock, 3, root="items")

    async with make_test_requester() as requester:
        plist = make_test_list(requester, _root="items", extra_attribs={"course_id": 1})
        pages = await fetch_pages(requester, plist, TEMPLATE, [2, 3])

    assert [record.id for record in pages[2].records] == [3, 4]
    assert all(record.course_id == 1 for record in pages[2].records)


def test_httpx_and_requests_parse_link_header_identically() -> None:
    """Pin the claim that PaginatedList's helpers can read an httpx response."""
    header = (
        '<{0}courses?page=3&per_page=2>; rel="next", '
        '<{0}courses?page=9&per_page=2>; rel="last"'
    ).format(settings.BASE_URL_WITH_VERSION)

    requests_response = requests.Response()
    requests_response.headers["Link"] = header
    httpx_response = httpx.Response(200, headers={"Link": header}, json=[])

    assert httpx_response.links == requests_response.links
