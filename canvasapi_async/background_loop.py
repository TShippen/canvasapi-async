"""An event loop on a background thread that synchronous code calls into.

The loop starts on the first call to :func:`run` and lives on a daemon thread
until :func:`shutdown` stops it. Coroutines reach it through an
:class:`anyio.from_thread.BlockingPortal`, so a synchronous caller gets a
result and an asynchronous library gets the loop it needs.

One lock covers all of the module's state: the portal, its thread and the
process that started them; the requesters, keyed by the Canvas instance they
talk to, and the process that registered them; and the settings
:func:`configure` stores. No portal call is ever made with the lock held.
"""

import atexit
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import Any, TypeVar

import anyio
from anyio.from_thread import BlockingPortal

from canvasapi_async.async_requester import AsyncRequester
from canvasapi_async.requester import Requester

logger = logging.getLogger(__name__)

T = TypeVar("T")

_LOOP_THREAD_NAME = "canvasapi-async-loop"

_lock = threading.Lock()

_portal: BlockingPortal | None = None
_thread: threading.Thread | None = None
_pid: int | None = None

_requesters: dict[tuple[str, str], AsyncRequester] = {}
_registry_pid: int | None = None

# The arguments configure() stores, passed to every AsyncRequester the
# registry creates. A setting that was never configured is absent, which
# leaves AsyncRequester's own default in place.
_settings: dict[str, Any] = {}


async def _close_requesters(requesters: list[AsyncRequester]) -> list[Exception]:
    """
    Close every requester, keeping whatever went wrong with each.

    Closing them in one coroutine rather than one call apiece leaves the
    portal a single question to answer, so a portal that has already stopped
    refuses once instead of once per requester.

    :param requesters: The requesters to close.
    """
    failures = []
    for requester in requesters:
        try:
            await requester.aclose()
        except Exception as failure:
            logger.error(
                "Failed to close the requester for %s",
                requester.original_url,
                exc_info=failure,
            )
            failures.append(failure)

    return failures


def _discard_stopped_loop(portal: BlockingPortal) -> None:
    """
    Drop the module's hold on a loop that has stopped on its own.

    A loop that ends without :func:`shutdown` stopping it leaves the module
    pointing at a portal that refuses every call, and clearing that is what
    lets the next :func:`run` start a fresh loop. The registered requesters
    go with it, since their clients belong to the loop that ended and a
    stopped portal cannot close them.

    :param portal: The portal the loop published, which is cleared only while
        it is still the module's own.
    """
    global _portal, _thread, _pid, _registry_pid

    with _lock:
        if _portal is not portal:
            return

        _portal, _thread, _pid, _registry_pid = None, None, None, None
        _requesters.clear()


def _own_portal() -> BlockingPortal | None:
    """
    The portal of this process's own loop, when it has one.

    A forked child inherits its parent's portal, which is not a loop it can
    call into. The caller holds the lock.
    """
    return _portal if _pid == os.getpid() else None


def _serve(ready: "Future[BlockingPortal]") -> None:
    """
    Run an event loop until its portal is stopped.

    This is the loop thread's target. The portal reaches the thread that
    started it through ``ready``, and a loop that ends for any other reason
    than :func:`shutdown` leaves nothing of itself behind.

    :param ready: The future to publish the portal through.
    """

    async def serve() -> None:
        async with BlockingPortal() as portal:
            ready.set_result(portal)
            await portal.sleep_until_stopped()

    try:
        anyio.run(serve)
    except BaseException as failure:
        # A failure before the portal is published belongs to whoever is
        # waiting on it, and handing it over is what keeps that caller from
        # waiting on a portal that never arrives. A failure after the portal
        # is published has no such caller and goes to the log.
        if not ready.done():
            ready.set_exception(failure)
            return

        logger.exception("Background event loop stopped with an error")

    _discard_stopped_loop(ready.result())


def configure(
    *,
    concurrency: int | None = None,
    quota_floor: int | None = None,
    timeout: float | None = None,
) -> None:
    """
    Set the arguments every requester the registry creates is built with.

    An argument left at None leaves that setting as it was. The settings
    outlive :func:`shutdown`, which stops the loop rather than forgetting what
    the caller asked for.

    :param concurrency: The number of requests allowed in flight at once.
    :param quota_floor: The value of Canvas's ``X-Rate-Limit-Remaining``
        header below which requests pause for a cooldown.
    :param timeout: The number of seconds a single request may take.
    """
    with _lock:
        if _own_portal() is not None:
            raise RuntimeError(
                "The event loop has already started; call shutdown() first."
            )

        for name, value in (
            ("concurrency", concurrency),
            ("quota_floor", quota_floor),
            ("timeout", timeout),
        ):
            if value is not None:
                _settings[name] = value


def requester_for(requester: Requester) -> AsyncRequester:
    """
    The asynchronous requester that talks to the same Canvas instance.

    There is one per Canvas URL and access token, built with whatever
    :func:`configure` has stored.

    :param requester: The synchronous requester to match.
    """
    global _registry_pid

    key = (requester.original_url, requester.access_token)
    with _lock:
        if _registry_pid != os.getpid():
            # A forked child inherits its parent's requesters, whose clients
            # belong to the parent's event loop.
            _requesters.clear()
            _registry_pid = os.getpid()

        existing = _requesters.get(key)
        if existing is None:
            existing = AsyncRequester(
                requester.original_url, requester.access_token, **_settings
            )
            _requesters[key] = existing

    return existing


def run(func: Callable[..., Awaitable[T]], *args: Any) -> T:
    """
    Run a coroutine on the background loop and return what it returns.

    The loop starts on the first call, and a process that inherited another
    one's loop starts its own. An exception the coroutine raises is raised
    here. A caller interrupted while it waits, by Ctrl-C or anything else,
    cancels the coroutine on its way out. A coroutine that takes the loop
    down with it leaves every other caller holding a
    ``concurrent.futures.CancelledError`` rather than its own exception.

    Only positional arguments reach the coroutine, which is what the portal
    accepts.

    :param func: The coroutine function to run.
    :param args: The positional arguments to call it with.
    """
    global _portal, _thread, _pid

    with _lock:
        portal = _own_portal()
        if portal is None:
            ready: Future[BlockingPortal] = Future()
            thread = threading.Thread(
                target=_serve, args=(ready,), name=_LOOP_THREAD_NAME, daemon=True
            )
            thread.start()
            # Nothing is stored until the portal arrives, so a startup failure
            # leaves the module as it was and raises here.
            portal = ready.result()
            _portal, _thread, _pid = portal, thread, os.getpid()
            logger.debug("Background event loop started")

    task = portal.start_task_soon(func, *args)
    try:
        return task.result()
    except BaseException:
        # Cancelling the future cancels the task on the loop, so a Ctrl-C
        # while a request is in flight stops the request.
        task.cancel()
        raise


def shutdown() -> None:
    """
    Close every registered requester and stop the background loop.

    Calling this twice, or from a process that inherited another one's loop,
    does nothing. The settings :func:`configure` stored are kept, and a later
    :func:`run` starts a fresh loop. Calling it from the loop's own thread
    raises, since a loop cannot wait for itself to stop.

    A :func:`run` already in flight on another thread is left to finish, and
    this waits for it. A :func:`run` that reaches the portal after it has
    stopped raises ``RuntimeError``.

    A loop that has stopped on its own is simply left stopped, and its
    requesters with it. Otherwise every requester is closed even if one of
    them fails, and the thread is joined even if a close fails in a way that
    cannot be caught. Each failure is logged, and the first is raised once
    the loop has stopped.
    """
    global _portal, _thread, _pid, _registry_pid

    with _lock:
        if threading.current_thread() is _thread:
            raise RuntimeError("shutdown() cannot be called from the loop's thread.")

        portal, thread, pid = _portal, _thread, _pid
        # Requesters another process registered are left alone, since their
        # clients belong to that process's event loop.
        requesters = list(_requesters.values()) if _registry_pid == os.getpid() else []
        _portal, _thread, _pid, _registry_pid = None, None, None, None
        _requesters.clear()

    if portal is None or thread is None or pid != os.getpid():
        return

    failures: list[Exception] = []
    try:
        failures = portal.call(_close_requesters, requesters)
        portal.call(portal.stop)
    except RuntimeError:
        # A portal that refuses a call has stopped already, which is all this
        # was going to ask of it. Its requesters stay open, since a loop that
        # has ended cannot close the clients it was running.
        logger.debug("Background event loop had stopped on its own")
    finally:
        thread.join()
        logger.debug("Background event loop stopped")

    if failures:
        raise failures[0]


# Closing connections at exit is tidiness rather than necessity: the loop runs
# on a daemon thread, and nothing it holds defines a finalizer that could hold
# the interpreter up. What the handler does add to exit is shutdown's wait for
# a request still in flight, so an exit under one is not immediate.
atexit.register(shutdown)
