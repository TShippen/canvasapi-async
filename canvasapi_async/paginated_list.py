from __future__ import annotations

import re
from typing import Any, Iterable, Iterator, Type, TypeVar

from canvasapi_async import background_loop
from canvasapi_async.concurrent_pagination import Page, fetch_pages, page_number
from canvasapi_async.exceptions import CanvasException

T = TypeVar("T")

# How a batch of pages grows as an access reads on, and how large it may get
# as a multiple of the requests the requester allows in flight at once. A
# batch that starts small keeps an access that stops early cheap, and one that
# grows keeps a long read to few round trips. The ceiling is tied to the
# requester's own limit, which holds a batch to that many requests at a time
# however wide it is, and every page asked for past the end of a list whose
# length Canvas did not report is a request thrown away.
BATCH_GROWTH = 2
BATCH_CEILING_MULTIPLE = 4


class PaginatedList(Iterable[T]):
    """
    Abstracts `pagination of Canvas API \
    <https://canvas.instructure.com/doc/api/file.pagination.html>`_.

    Records are loaded in order and held in one flat list, so an index is
    always the index of a record that was really read. An endpoint that
    numbers its pages has the pages ahead fetched together on the background
    event loop; one that paginates by bookmark cursor is followed a page at a
    time, since only the page in hand says where the next one is.
    """

    def __getitem__(self, index):
        assert isinstance(index, (int, slice))
        if isinstance(index, int):
            if index < 0:
                raise IndexError("Cannot negative index a PaginatedList")
            self._load(index + 1)
            return self._elements[index]
        else:
            return self._Slice(self, index)

    def __init__(
        self,
        content_class: Type[T],
        requester,
        request_method,
        first_url,
        extra_attribs=None,
        _root=None,
        _url_override=None,
        _kwargs=None,
        **kwargs,
    ):
        """
        :param content_class: The expected type to return in the list.
        :type content_class: class
        :param requester: The requester to pass HTTP requests through.
        :type requester: :class:`canvasapi_async.requester.Requester`
        :param request_method: HTTP request method
        :type request_method: str
        :param first_url: Canvas endpoint for the initial request
        :type first_url: str
        :param extra_attribs: Extra data to include in the request
        :type extra_attribs: dict
        :param _root: Specify a nested property from Canvas to use for the resulting list.
        :type _root: str
        :param _url_override: "new_quizzes" or "graphql" for specific Canvas endpoints.

        Other URLs may be specified for third-party requests.
        :type _url_override: str
        :rtype: :class:`canvasapi_async.paginated_list.PaginatedList` of type content_class
        :param _kwargs: A list of 2-tuples representing processed
            keyword arguments to be sent to Canvas as params or data.
        :type _kwargs: list[tuple[str, Any]]
        """
        self._elements = list()

        self._requester = requester
        self._content_class = content_class
        self._first_url = first_url
        _kwargs = _kwargs or []
        for key, value in _kwargs:
            if key == "per_page":
                break
        else:
            # change kwargs such that if per_page is given as a keyword argument,
            # we don't override it.
            kwargs.setdefault("per_page", 100)
        self._first_params = {"_kwargs": _kwargs, **kwargs}
        # Stands in until page one says how many records a page really holds.
        self._page_size = 1
        self._scheme: str | None = None
        self._template: str | None = None
        self._next_page = 0
        self._next_url: str | None = None
        self._last_page: int | None = None
        self._batch = 0
        self._complete = False
        self._extra_attribs = extra_attribs or {}
        self._request_method = request_method
        self._root = _root
        self._url_override = _url_override

    def __iter__(self) -> Iterator[T]:
        index = 0
        while True:
            if index >= len(self._elements):
                self._load_more()
                if index >= len(self._elements):
                    return

            yield self._elements[index]
            index += 1

    def __repr__(self):
        return "<PaginatedList of type {}>".format(self._content_class.__name__)

    def _fetch(self, wanted: int | None) -> None:
        """
        Make the next request the list owes, or the next batch of them.

        Page one and every page of a bookmark-paginated list go one at a time
        through the requester the list was built with, whatever an access asks
        for, because nothing says where the page after this one is until it
        arrives.

        :param wanted: How many numbered pages to ask for at once, or None for
            the next batch of a growing sequence.
        """
        if self._scheme is None:
            self._load_first()
        elif self._scheme == "bookmark":
            self._load_next()
        else:
            self._load_batch(wanted)

    def _is_larger_than(self, index: int) -> bool:
        """
        Whether the list holds an index, reading further pages to find out.
        """
        while len(self._elements) <= index and not self._complete:
            self._load_more()

        return len(self._elements) > index

    def _load(self, needed: int) -> None:
        """
        Hold at least ``needed`` records, or reach the end of the list.

        :param needed: The number of records the access needs.
        """
        while not self._complete and len(self._elements) < needed:
            short = needed - len(self._elements)
            # How many pages are still wanted is only an estimate, taken from
            # what page one held. A page shorter than that makes a round ask
            # for too few, and the loop simply goes round again.
            self._fetch((short + self._page_size - 1) // self._page_size)

    def _load_batch(self, wanted: int | None) -> None:
        """
        Fetch the next run of pages of a numbered list, all at once.

        :param wanted: How many pages to ask for, or None for the next batch
            of a growing sequence.
        """
        requester = background_loop.requester_for(self._requester)
        ceiling = requester.concurrency * BATCH_CEILING_MULTIPLE
        if wanted is None:
            self._batch = min(
                self._batch * BATCH_GROWTH if self._batch else requester.concurrency,
                ceiling,
            )
            wanted = self._batch

        # A round always asks for at least one page, so no arithmetic on the
        # caller's side can leave the loading loop turning without a request.
        last = self._next_page + max(min(wanted, ceiling), 1) - 1
        if self._last_page is not None:
            last = min(last, self._last_page)

        self._take(
            background_loop.run(
                fetch_pages,
                requester,
                self,
                self._template,
                range(self._next_page, last + 1),
            )
        )

    def _load_first(self) -> None:
        """
        Request page one through the requester the list was built with, and
        read what its response says about the rest of the list.
        """
        params = dict(self._first_params)
        # Requester._normalize_params extends the list it is handed in place,
        # so a page one asked for again after a failure would send every bare
        # keyword argument a second time.
        params["_kwargs"] = list(params["_kwargs"])

        response = self._requester.request(
            self._request_method, self._first_url, _url=self._url_override, **params
        )
        data = response.json()
        records = self._records_from(data)
        self._read_links(response, data)

        # Canvas names the number of the final page on a response that holds
        # records; on one that holds none it names the page that was asked
        # for. Only page one's is read, and only to keep a batch from running
        # past the end of the list.
        final = response.links.get("last")
        if records and final:
            self._last_page = page_number(final["url"])

        # How many records a page holds is taken from the page that arrived
        # rather than from what was asked for. It is only an estimate of how
        # many pages a later access wants: getting it wrong costs another
        # round of requests, never a wrong record.
        self._page_size = max(len(records), 1)

        self._elements += records

    def _load_more(self) -> None:
        """
        Hold more records than are held now, unless the list has no more.
        """
        held = len(self._elements)
        while not self._complete and len(self._elements) == held:
            self._fetch(None)

    def _load_next(self) -> None:
        """
        Follow the list's next link to the page after the one in hand.
        """
        response = self._requester.request(
            self._request_method, self._next_url, _url=self._url_override
        )
        data = response.json()
        records = self._records_from(data)
        self._read_links(response, data)

        self._elements += records

    def _next_link_from(self, response: Any, data: Any) -> str | None:
        """
        Find the URL of the next page in a response's headers or its body.
        """
        # Check the response headers first. This is the normal Canvas convention
        # for pagination, but there are endpoints which return a `meta` property
        # for pagination instead.
        # See https://github.com/ucfopen/canvasapi/discussions/605
        if response.links:
            next_link = response.links.get("next")
        elif isinstance(data, dict) and "meta" in data:
            # requests parses headers into dicts, this returns the same
            # structure so the regex will still work.
            try:
                next_link = {"url": data["meta"]["pagination"]["next"], "rel": "next"}
            except KeyError:
                next_link = None
        else:
            next_link = None

        return next_link["url"] if next_link else None

    def _read_links(self, response: Any, data: Any) -> None:
        """
        Read what a sequentially fetched page says about the rest of the list.

        :param response: The response the page arrived in.
        :param data: The decoded body of that response.
        """
        next_url = self._next_link_from(response, data)
        # The link is stripped before anything is stored, so a URL that does
        # not match the requester's bases raises with the list left as it was
        # rather than pointing at a page it has no way to request.
        stripped = self._strip_base(next_url) if next_url else None

        if stripped is None:
            self._complete = True
            return

        numbered = page_number(stripped)
        if numbered is None:
            self._scheme = "bookmark"
            self._next_url = stripped
            return

        self._scheme = "numeric"
        self._template = stripped
        self._next_page = numbered

    def _records_from(self, data: Any) -> list[T]:
        """
        Build content objects from a page of response data.
        """
        content = []

        if self._root:
            try:
                data = data[self._root]
            except KeyError:
                raise ValueError(
                    "The key <{}> does not exist in the response.".format(self._root)
                )

        for element in data:
            if element is not None:
                element.update(self._extra_attribs)
                content.append(self._content_class(self._requester, element))

        return content

    def _strip_base(self, url: str) -> str:
        """
        Strip the requester's base or new-quizzes URL off the front of a URL.
        """
        regex = r"(?:{}|{})(.*)".format(
            re.escape(self._requester.base_url),
            re.escape(self._requester.new_quizzes_url),
        )

        return re.search(regex, url).group(1)

    def _take(self, fetched: dict[int, Page]) -> None:
        """
        Append a batch of fetched pages to the list, in page order.

        The first page of the batch holding no records, or holding records and
        carrying no next link, is the end of the list, and whatever the batch
        holds past it is dropped.

        :param fetched: The pages the batch returned, by page number.
        """
        for number, page in sorted(fetched.items()):
            if page.current is not None and page.current != number:
                raise CanvasException(
                    "Asked Canvas for page {} and it answered with page {}".format(
                        number, page.current
                    )
                )

            if not page.records:
                self._complete = True
                return

            self._elements += page.records
            self._next_page = number + 1

            if page.next_url is None:
                self._complete = True
                return

        if self._last_page is not None and self._next_page > self._last_page:
            self._complete = True

    class _Slice(object):
        def __init__(self, the_list, the_slice):
            self._list = the_list
            self._start = the_slice.start or 0
            self._stop = the_slice.stop
            self._step = the_slice.step or 1

            if self._start < 0 or (self._stop is not None and self._stop < 0):
                raise IndexError("Cannot negative index a PaginatedList slice")

        def __iter__(self):
            if self._stop is not None and self._stop > self._start:
                # A slice that knows where it ends says so in one go, so the
                # pages it covers are asked for together rather than one at a
                # time as the indices come round.
                self._list._load(self._stop)

            index = self._start
            while not self._finished(index):
                if self._list._is_larger_than(index):
                    yield self._list[index]
                    index += self._step
                else:
                    return

        def _finished(self, index):
            return self._stop is not None and index >= self._stop
