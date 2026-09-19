"""Concurrent fetching of the pages of a paginated Canvas list."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import anyio

from canvasapi_async.async_requester import AsyncRequester

if TYPE_CHECKING:
    from canvasapi_async.paginated_list import PaginatedList


class Page:
    """
    One page of a paginated Canvas list.

    The records are what the list's own extraction made of the response body,
    so a page of a root-bearing endpoint is empty when the root holds nothing.
    An empty page is what bounds the end of a list whose length Canvas does
    not report.
    """

    __slots__ = ("current", "next_url", "records")

    def __init__(
        self,
        records: list[Any],
        next_url: str | None,
        current: int | None,
    ) -> None:
        """
        :param records: The content objects the response body held.
        :param next_url: The stripped URL of the page after this one, or None
            when the response carried no next link.
        :param current: The page the response says it is, which lets a caller
            check that Canvas answered the page that was asked for. It is None
            on a response carrying no ``current`` link, and on one whose
            ``current`` link holds a bookmark cursor rather than a number.
        """
        self.records = records
        self.next_url = next_url
        self.current = current


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
    current_link = response.links.get("current")

    return Page(
        records=plist._records_from(data),
        next_url=plist._strip_base(next_link) if next_link else None,
        current=page_number(current_link["url"]) if current_link else None,
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
