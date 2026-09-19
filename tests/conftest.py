"""Fixtures every test in the suite runs under."""

from collections.abc import Iterator

import httpx
import pytest
import respx

from canvasapi_async import background_loop
from tests import util


@pytest.fixture(autouse=True)
def httpx_fixtures() -> Iterator[None]:
    """
    Answer httpx requests from the fixtures a test registers, and leave no
    event loop running behind it.

    The router covers every test rather than the paginating ones alone,
    because a list that pages concurrently reaches httpx from wherever it is
    built. A test that registered no fixtures has its requests handed on to
    whatever router it started for itself: returning None from the side effect
    leaves the route unmatched, and respx passes an unmatched request to the
    next router.
    """
    util.HTTPX_FIXTURES.clear()

    async def answer(request: httpx.Request) -> httpx.Response | None:
        if not util.HTTPX_FIXTURES:
            return None

        return util.httpx_fixture_response(request)

    router = respx.mock(assert_all_called=False)
    util.HTTPX_ROUTE = router.route().mock(side_effect=answer)
    router.start()

    try:
        yield
    finally:
        try:
            background_loop.shutdown()
        finally:
            router.stop()
            util.HTTPX_ROUTE = None
            util.HTTPX_FIXTURES.clear()
