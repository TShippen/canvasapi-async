"""Concurrent fetching of the pages of a paginated Canvas list."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import anyio

from canvasapi_async.async_requester import AsyncRequester

if TYPE_CHECKING:
    from canvasapi_async.paginated_list import PaginatedList


@dataclass(frozen=True)
class Page:
    """
    One page of a paginated Canvas list.

    The records are what the list's own extraction made of the response body,
    so a page of a root-bearing endpoint is empty when the root holds nothing.
    An empty page is what bounds the end of a list whose length Canvas does
    not report.
    """

    number: int
    records: list[Any]
    next_url: str | None


def page_number(url: str) -> int | None:
    """
    The page a URL asks for, when it asks for one by number.

    Endpoints that paginate by bookmark carry a cursor in place of a number,
    and there is nothing to read from one.

    :param url: The URL to read the ``page`` query parameter of.
    """
    values = parse_qs(urlparse(url).query).get("page")
    if not values:
        return None

    try:
        return int(values[0])
    except ValueError:
        return None


def page_url(template: str, page: int) -> str:
    """
    A page URL built by swapping a page number into a template.

    :param template: A stripped page URL carrying a ``page`` query parameter.
    :param page: The page number to ask for.
    """
    path, _, query = template.partition("?")
    pairs = [
        "page={}".format(page) if pair.startswith("page=") else pair
        for pair in query.split("&")
    ]

    return "{}?{}".format(path, "&".join(pairs))


async def _fetch_page(
    requester: AsyncRequester,
    plist: PaginatedList[Any],
    template: str,
    number: int,
) -> Page:
    """
    Request one page of a list and read the response the way the list does.

    :param requester: The requester to send the request through.
    :param plist: The list the page belongs to.
    :param template: A stripped page URL to take the query from.
    :param number: The page number to request.
    """
    response = await requester.request_async(
        plist._request_method, page_url(template, number), _url=plist._url_override
    )
    data = response.json()
    next_link = plist._next_link_from(response, data)

    return Page(
        number=number,
        records=plist._records_from(data),
        next_url=plist._strip_base(next_link) if next_link else None,
    )


async def fetch_pages(
    requester: AsyncRequester,
    plist: PaginatedList[Any],
    template: str,
    pages: Iterable[int],
) -> dict[int, Page]:
    """
    Fetch the named pages of a list at once, keyed by page number.

    Every page is requested in one task group, so the first failure cancels
    the requests still in flight. How many run at once is the requester's
    concern, not this function's.

    :param requester: The requester to send the requests through.
    :param plist: The list the pages belong to.
    :param template: A stripped page URL to take the query from.
    :param pages: The page numbers to request.
    """
    fetched: dict[int, Page] = {}
    failures: list[Exception] = []

    async def fetch(number: int) -> None:
        # Nothing escapes a page task: a caller wants the Canvas exception the
        # requester raised, and cancelling the scope here is what stops the
        # sibling requests. A task cancelled that way is not recorded as a
        # failure, since the backend's cancellation is not an Exception.
        try:
            fetched[number] = await _fetch_page(requester, plist, template, number)
        except Exception as failure:
            failures.append(failure)
            tasks.cancel_scope.cancel()

    async with anyio.create_task_group() as tasks:
        for number in pages:
            tasks.start_soon(fetch, number)

    if failures:
        raise failures[0]

    return dict(sorted(fetched.items()))


def _bounds(
    pages: Mapping[int, Page], start: int
) -> tuple[int, int | None, int | None]:
    """
    Read what the pages held so far say about where the list ends.

    Returns the highest page holding records, the lowest page holding none,
    and the number of the final page once a page settles it.

    :param pages: The pages fetched so far, keyed by page number.
    :param start: The first page number this fetch covers.
    """
    highest_filled = start - 1
    lowest_empty: int | None = None
    final: int | None = None

    for number, page in pages.items():
        if not page.records:
            # A page past the end of a list holds no records, which puts a
            # ceiling on where the list ends. Canvas answers such a page with
            # a `last` link naming the page that was requested rather than the
            # end of the list, and that link is never read.
            lowest_empty = number if lowest_empty is None else min(lowest_empty, number)
            continue

        highest_filled = max(highest_filled, number)
        if page.next_url is None:
            # A page holding records and carrying no next link is the last
            # page of the list.
            final = number

    return highest_filled, lowest_empty, final


def _midpoints(highest_filled: int, lowest_empty: int, cap: int) -> list[int]:
    """
    Up to ``cap`` evenly spaced page numbers strictly between the bounds.

    The list is empty once the bounds meet, which is what ends the bisection.

    :param highest_filled: The highest page known to hold records.
    :param lowest_empty: The lowest page known to hold none.
    :param cap: The most page numbers to return.
    """
    between = range(highest_filled + 1, lowest_empty)
    if len(between) <= cap:
        return list(between)

    spacing = len(between) / (cap + 1)

    return [between[round(spacing * step)] for step in range(1, cap + 1)]


def _with_records(pages: Mapping[int, Page], final: int) -> dict[int, Page]:
    """
    The pages up to the end of the list that hold records, in page order.

    :param pages: The pages fetched, keyed by page number.
    :param final: The number of the list's final page.
    """
    return {
        number: page
        for number, page in sorted(pages.items())
        if page.records and number <= final
    }


async def fetch_from(
    requester: AsyncRequester,
    plist: PaginatedList[Any],
    template: str,
    start: int,
    last: int | None,
    cap: int,
    stride_start: int = 2,
    stride_growth: float = 1.5,
) -> dict[int, Page]:
    """
    Fetch every page of a list from ``start`` to its end.

    When Canvas has reported the number of the final page, the whole range
    goes out in one batch. When it has not, a first batch of ``cap`` pages
    starts the search, further batches probe beyond the pages already seen at
    a stride that grows each round until one of them bounds the end, bisection
    between the bounds narrows the end down to a single page, and a last batch
    fills in the pages the probe skipped over.

    :param requester: The requester to send the requests through.
    :param plist: The list the pages belong to.
    :param template: A stripped page URL to take the query from.
    :param start: The first page number to fetch.
    :param last: The number of the list's final page when Canvas reported one,
        or None when the end has to be found.
    :param cap: The number of pages a batch requests.
    :param stride_start: The gap between the pages of the first probing batch.
    :param stride_growth: The factor the stride grows by after each probing
        batch, rounded up.
    """
    if last is not None:
        return _with_records(
            await fetch_pages(requester, plist, template, range(start, last + 1)), last
        )

    pages = await fetch_pages(requester, plist, template, range(start, start + cap))
    highest_filled, lowest_empty, final = _bounds(pages, start)

    stride = stride_start
    while final is None and lowest_empty is None:
        probe = [highest_filled + stride * step for step in range(1, cap + 1)]
        pages.update(await fetch_pages(requester, plist, template, probe))
        stride = ceil(stride * stride_growth)
        highest_filled, lowest_empty, final = _bounds(pages, start)

    while final is None and lowest_empty is not None:
        probe = _midpoints(highest_filled, lowest_empty, cap)
        if not probe:
            break
        pages.update(await fetch_pages(requester, plist, template, probe))
        highest_filled, lowest_empty, final = _bounds(pages, start)

    if final is None:
        final = highest_filled

    missing = [number for number in range(start, final + 1) if number not in pages]
    pages.update(await fetch_pages(requester, plist, template, missing))

    return _with_records(pages, final)
