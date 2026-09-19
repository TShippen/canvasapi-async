"""Asynchronous transport for Canvas API requests."""

import logging
import random
import time
from types import TracebackType
from typing import Any, NoReturn
from urllib.parse import urlencode

import anyio
import httpx

from canvasapi_async.requester import Requester

logger = logging.getLogger(__name__)

# Seconds to hold requests back after Canvas reports a low rate limit quota.
QUOTA_COOLDOWN_SECONDS = 1.0

# Number of times a throttled request is retried before its error is raised.
RATE_LIMIT_RETRIES = 3

# Delay before the first retry of a throttled request that carries no usable
# Retry-After header. Each further attempt doubles it.
BACKOFF_BASE_SECONDS = 0.5

# Upper bound of the random jitter added to each backoff delay, so that
# requests throttled together do not all return at the same moment.
BACKOFF_JITTER_SECONDS = 0.25

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

METHODS_WITH_FORM_BODY = ("POST", "PUT", "PATCH", "DELETE")


class AsyncRequester(Requester):
    """
    Handles HTTP requests to Canvas on an event loop.

    Request preparation, response logging, and error handling are inherited
    from :class:`canvasapi_async.requester.Requester`. What changes is the
    transport: an :class:`httpx.AsyncClient` in place of a
    :class:`requests.Session`, governed by a cap on the requests in flight at
    once, a pause once Canvas reports a low rate limit quota, and retries of
    throttled requests.

    Requests are made with :meth:`request_async`. The synchronous
    :meth:`request` raises, and file uploads stay on the synchronous requester.
    """

    async def __aenter__(self) -> "AsyncRequester":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        concurrency: int = 4,
        quota_floor: int = 150,
        timeout: float = 60.0,
    ) -> None:
        """
        :param base_url: The base URL of the Canvas instance's API.
        :param access_token: The API key to authenticate requests with.
        :param concurrency: The number of requests allowed in flight at once.
        :param quota_floor: The value of Canvas's ``X-Rate-Limit-Remaining``
            header below which requests pause for a cooldown.
        :param timeout: The number of seconds a single request may take.
        """
        # Preserve the original base url and add "/api/v1" to it
        self.original_url = base_url
        self.base_url = base_url + "/api/v1/"
        self.new_quizzes_url = base_url + "/api/quiz/v1/"
        self.graphql = base_url + "/api/graphql"
        self.access_token = access_token
        self._cache: list[httpx.Response] = []

        self._concurrency = concurrency
        self._quota_floor = quota_floor
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._limiter = anyio.Semaphore(concurrency)
        self._resume_at: float | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        """
        Return this requester's client, creating it on first use.

        Creating it here rather than in ``__init__`` means the client belongs
        to the event loop that runs the requests.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)

        return self._client

    def _merge_query(self, url: str, params: list[tuple[str, Any]]) -> str:
        """
        Append parameters to whatever query a URL already carries.

        httpx replaces a URL's query with the parameters it is handed, where
        requests appends them, so a URL that carries a query of its own has to
        arrive with the two already joined. A fragment stays at the end, past
        the query it follows.

        :param url: The full URL to request.
        :param params: The processed keyword arguments, as 2-tuples.
        """
        if not params:
            return url

        addressed, hash_sign, fragment = url.partition("#")
        path, _, query = addressed.partition("?")
        encoded = urlencode(params, doseq=True)
        if query:
            encoded = "{}&{}".format(query, encoded)

        return "{}?{}{}{}".format(path, encoded, hash_sign, fragment)

    def _record_quota(self, response: httpx.Response) -> None:
        """
        Note what a response reports about the remaining rate limit quota.

        A quota below the floor starts a cooldown that later requests wait
        out. Only a quota at or above the floor clears it; a quota that is
        absent or does not parse leaves it as it was.

        :param response: The response whose rate limit headers to read.
        """
        cost = response.headers.get("X-Request-Cost")
        if cost is not None:
            logger.debug("Request cost: %s", cost)

        remaining = response.headers.get("X-Rate-Limit-Remaining")
        if remaining is None:
            return

        try:
            quota = float(remaining)
        except ValueError:
            logger.warning(
                "Ignoring unparsable X-Rate-Limit-Remaining header: %s", remaining
            )
            return

        if quota < self.quota_floor:
            logger.warning(
                "Rate limit quota down to %s; pausing requests for %s seconds",
                remaining,
                QUOTA_COOLDOWN_SECONDS,
            )
            self._resume_at = time.monotonic() + QUOTA_COOLDOWN_SECONDS
            return

        self._resume_at = None

    def _retry_delay(self, attempt: int, response: httpx.Response) -> float:
        """
        Return the number of seconds to wait before retrying a request.

        :param attempt: The number of retries already made for the request.
        :param response: The throttled response that prompted the retry.
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                logger.debug("Ignoring unparsable Retry-After header: %s", retry_after)

        backoff: float = BACKOFF_BASE_SECONDS * 2**attempt
        return backoff + random.uniform(0, BACKOFF_JITTER_SECONDS)

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict[str, str],
        params: list[tuple[str, Any]],
        json: Any,
    ) -> httpx.Response:
        """
        Issue a single request, carrying the parameters where the method wants
        them.

        :param client: The client to send the request with.
        :param method: The HTTP method for the request.
        :param url: The full URL to request.
        :param headers: The HTTP headers to send with the request.
        :param params: The processed keyword arguments, as 2-tuples.
        :param json: JSON-encoded data to send in the body of a POST request,
            or a false value to send the parameters as form data instead.
        """
        if method == "GET":
            return await client.get(self._merge_query(url, params), headers=headers)

        if method == "POST" and json:
            return await client.post(
                self._merge_query(url, params), headers=headers, json=json
            )

        if method not in METHODS_WITH_FORM_BODY:
            raise ValueError("Unsupported HTTP method: {}".format(method))

        if method == "POST" and any(field == "file" for field, _ in params):
            raise NotImplementedError(
                "File uploads are only supported by the synchronous Requester."
            )

        # httpx form-encodes mappings only, and a mapping cannot carry the same
        # key twice, so the 2-tuples are encoded here. The body is what requests
        # encodes for the parameters that arrive here, whose None values
        # request_async has already dropped. With no parameters the headers
        # differ: all four methods add a Content-Type that requests omits, and
        # DELETE also sends no Content-Length where requests sends zero.
        form_headers = dict(headers)
        form_headers["Content-Type"] = FORM_CONTENT_TYPE

        return await client.request(
            method, url, headers=form_headers, content=urlencode(params, doseq=True)
        )

    async def _wait_for_quota(self) -> None:
        """
        Wait out any cooldown that a previous response started.

        A response that arrives during the wait can push the cooldown back, so
        the deadline is read again after every sleep.
        """
        while self._resume_at is not None:
            delay = self._resume_at - time.monotonic()
            if delay <= 0:
                return

            await anyio.sleep(delay)

    async def aclose(self) -> None:
        """
        Close the underlying client, if one has been created.
        """
        if self._client is None:
            return

        await self._client.aclose()
        self._client = None

    @property
    def concurrency(self) -> int:
        """
        The number of requests allowed in flight at once.
        """
        return self._concurrency

    @property
    def quota_floor(self) -> int:
        """
        The remaining rate limit quota below which requests pause.
        """
        return self._quota_floor

    def request(
        self,
        method: str,
        endpoint: str | None = None,
        headers: dict[str, str] | None = None,
        use_auth: bool = True,
        _url: str | None = None,
        _kwargs: list[tuple[str, Any]] | None = None,
        json: Any = False,
        **kwargs: Any,
    ) -> NoReturn:
        """
        Refuse a synchronous request.

        The arguments match
        :meth:`canvasapi_async.requester.Requester.request` so that a
        synchronous call made by mistake fails with this message.
        """
        raise NotImplementedError(
            "AsyncRequester has no synchronous request; await request_async instead."
        )

    async def request_async(
        self,
        method: str,
        endpoint: str | None = None,
        headers: dict[str, str] | None = None,
        use_auth: bool = True,
        _url: str | None = None,
        _kwargs: list[tuple[str, Any]] | None = None,
        json: Any = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make a request to the Canvas API and return the response.

        :param method: The HTTP method for the request.
        :param endpoint: The endpoint to call.
        :param headers: Optional HTTP headers to be sent with the request.
        :param use_auth: Optional flag to remove the authentication
            header from the request.
        :param _url: Optional argument to specify a request type to Canvas
            or to send a request to a URL outside of the Canvas API.
            If set to "new_quizzes", the new quizzes endpoint will be used.
            If set to "graphql", a graphql POST request will be sent.
            If any string URL is provided, it will be used instead of the
            base REST URL.
            If omitted or set to None, the base_url for the instance REST
            endpoint will be used.
            If this is selected and an endpoint is provided, the endpoint
            will be ignored and only the `_url` argument will be used..
        :param _kwargs: A list of 2-tuples representing processed
            keyword arguments to be sent to Canvas as params or data.
        :param json: Whether or not to treat the data as json instead of form
            data. Currently only the POST request of GraphQL is using this
            parameter. For all other methods it's just passed and ignored.
        """
        full_url = self._resolve_url(endpoint, _url)
        request_headers = self._build_headers(headers, use_auth)

        # httpx sends a parameter with a value of None as an empty string,
        # where requests drops it. Dropping it here keeps the two on the same
        # wire.
        params = [
            (key, value)
            for key, value in self._normalize_params(_kwargs, kwargs)
            if value is not None
        ]

        client = self._ensure_client()

        attempt = 0
        while True:
            # The permit is taken before the cooldown is waited out, so that a
            # request already queued for a permit still re-checks the pause
            # before it sends. A paused request holds its permit while it waits.
            # The response is recorded before the permit is released, so the
            # next holder sees a pause this response started.
            async with self._limiter:
                await self._wait_for_quota()
                self._log_request(method, full_url, request_headers, params, json)
                response = await self._send(
                    client, method, full_url, request_headers, params, json
                )
                self._log_response(method, full_url, response)
                self._record_quota(response)

            if response.status_code != 429 or attempt >= RATE_LIMIT_RETRIES:
                break

            await anyio.sleep(self._retry_delay(attempt, response))
            attempt += 1

        self._remember(response)
        self._raise_for_status(response)

        return response

    @property
    def timeout(self) -> float:
        """
        The number of seconds a single request may take.
        """
        return self._timeout
