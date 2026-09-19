import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import CancelledError, Future
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import respx
from anyio import to_thread
from anyio.from_thread import BlockingPortal

from canvasapi_async import background_loop
from canvasapi_async.requester import Requester
from tests import settings

LOGGER_NAME = "canvasapi_async.background_loop"

REPO_ROOT = Path(__file__).resolve().parents[1]

# The body every subprocess script starts with: it uses the loop and leaves it
# running, which is what the exit paths below are about.
USES_THE_LOOP = """
from canvasapi_async import background_loop


async def seven():
    return 7


assert background_loop.run(seven) == 7
"""

# A script that makes a real request to a server of its own and never closes
# the client, so the interpreter exits with an httpx client still open.
LEAVES_A_CLIENT_OPEN = """
import http.server
import threading

from canvasapi_async import background_loop
from canvasapi_async.async_requester import AsyncRequester


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"[]"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

requester = AsyncRequester("http://127.0.0.1:{}".format(server.server_port), "token")
response = background_loop.run(requester.request_async, "GET", "courses")

assert response.status_code == 200
assert requester._client is not None
"""

# A script whose coroutine leaves by SystemExit, which takes the loop down
# with it and leaves the exit handler a portal that refuses every call.
LEAVES_BY_SYSTEM_EXIT = """
from canvasapi_async import background_loop


async def leave():
    raise SystemExit(9)


background_loop.run(leave)
"""

# A script that interrupts itself while it waits on the loop, which is what a
# Ctrl-C during a fetch does. It runs out of process so the signal reaches no
# other test.
SIGNALS_ITSELF = """
import os
import signal
import threading

import anyio

from canvasapi_async import background_loop

cancelled = threading.Event()


async def wait_to_be_cancelled():
    try:
        await anyio.sleep(30)
    except anyio.get_cancelled_exc_class():
        cancelled.set()
        raise


threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGINT)).start()

try:
    background_loop.run(wait_to_be_cancelled)
except KeyboardInterrupt:
    print("interrupted")

assert cancelled.wait(10)
print("cancelled")
"""

# A script whose forked pool workers each use the loop they inherited state
# for. Running it out of process keeps the fork DeprecationWarning that
# Python 3.12 and later emit out of this suite's output.
FORK_POOL = """
import multiprocessing
import os

from canvasapi_async import background_loop
from canvasapi_async.requester import Requester


async def own_pid():
    return os.getpid()


def work(task):
    pid = background_loop.run(own_pid)
    requester = background_loop.requester_for(Requester("https://example.com", "token"))

    return task, pid, requester.original_url


if __name__ == "__main__":
    parent = background_loop.run(own_pid)
    assert parent == os.getpid()

    with multiprocessing.get_context("fork").Pool(2) as pool:
        results = pool.map(work, range(4))

    assert [task for task, _, _ in results] == [0, 1, 2, 3]
    assert all(pid != parent for _, pid, _ in results)
    assert all(url == "https://example.com" for _, _, url in results)
"""


@pytest.fixture(autouse=True)
def stop_the_loop() -> Iterator[None]:
    """Leave no loop thread running and no configured setting behind."""
    configured = dict(background_loop._settings)

    yield

    background_loop.shutdown()
    for thread in loop_threads():
        thread.join(10)
    assert loop_threads() == []

    background_loop._settings.clear()
    background_loop._settings.update(configured)


def loop_threads() -> list[threading.Thread]:
    """Every live thread a loop of this module's making runs on."""
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == background_loop._LOOP_THREAD_NAME
    ]


def logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The messages this module's logger recorded."""
    return [
        record.getMessage() for record in caplog.records if record.name == LOGGER_NAME
    ]


async def seven() -> int:
    return 7


async def three() -> int:
    return 3


def make_requester(token: str = settings.API_KEY) -> Requester:
    """Build a synchronous requester pointed at the fake Canvas instance."""
    return Requester(settings.BASE_URL, token)


def no_portal() -> BlockingPortal:
    """Fail the way a loop that cannot start does."""
    raise RuntimeError("no portal today")


def run_script(tmp_path: Path, source: str) -> "subprocess.CompletedProcess[str]":
    """
    Run a script under the project interpreter and return how it went.

    :param tmp_path: The directory to write the script to.
    :param source: The script to run.
    """
    script = tmp_path / "script.py"
    script.write_text(source, encoding="utf-8")

    return subprocess.run(
        [sys.executable, str(script)],
        timeout=20,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_run_starts_loop_lazily() -> None:
    assert background_loop._portal is None

    assert background_loop.run(seven) == 7

    assert background_loop._portal is not None


def test_loop_thread_is_a_daemon() -> None:
    background_loop.run(seven)

    assert background_loop._thread is not None
    assert background_loop._thread.daemon is True


def test_requester_for_is_keyed_by_url_and_token() -> None:
    first = background_loop.requester_for(make_requester())
    again = background_loop.requester_for(make_requester())
    other = background_loop.requester_for(make_requester(token="another-token"))

    assert again is first
    assert other is not first


def test_configure_applies_to_new_requesters() -> None:
    background_loop.configure(concurrency=2)

    assert background_loop.requester_for(make_requester()).concurrency == 2


def test_configure_leaves_an_omitted_setting_alone() -> None:
    background_loop.configure(concurrency=2, quota_floor=7)
    background_loop.configure(concurrency=5)

    requester = background_loop.requester_for(make_requester())

    assert (requester.concurrency, requester.quota_floor) == (5, 7)


def test_configure_after_start_raises() -> None:
    background_loop.run(seven)

    with pytest.raises(RuntimeError, match="shutdown"):
        background_loop.configure(concurrency=1)


def test_configure_after_shutdown_is_allowed() -> None:
    background_loop.run(seven)
    background_loop.shutdown()

    background_loop.configure(concurrency=3)

    assert background_loop.requester_for(make_requester()).concurrency == 3


def test_configure_in_another_process_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_loop.run(seven)

    # A forked child inherits the parent's portal, which is not a loop of its
    # own and so is no reason to refuse.
    monkeypatch.setattr(os, "getpid", lambda: 1)
    background_loop.configure(concurrency=6)

    assert background_loop.requester_for(make_requester()).concurrency == 6


def test_configured_settings_survive_a_shutdown() -> None:
    background_loop.configure(timeout=1.5)
    background_loop.run(seven)

    background_loop.shutdown()

    assert background_loop.requester_for(make_requester()).timeout == 1.5


def test_shutdown_is_idempotent() -> None:
    background_loop.run(seven)

    background_loop.shutdown()
    background_loop.shutdown()

    assert background_loop._portal is None


@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
def test_shutdown_closes_requesters(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))
    requester = background_loop.requester_for(make_requester())
    background_loop.run(requester.request_async, "GET", "courses")
    client = requester._client

    background_loop.shutdown()

    assert client is not None
    assert client.is_closed


def test_shutdown_logs_every_close_failure_and_raises_the_first(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    first = background_loop.requester_for(make_requester(token="first-token"))
    second = background_loop.requester_for(make_requester(token="second-token"))
    background_loop.run(seven)
    thread = background_loop._thread

    async def refuse_to_close() -> None:
        raise OSError("the socket is stuck")

    async def refuse_as_well() -> None:
        raise OSError("this one too")

    monkeypatch.setattr(first, "aclose", refuse_to_close)
    monkeypatch.setattr(second, "aclose", refuse_as_well)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(OSError, match="the socket is stuck"):
            background_loop.shutdown()

    complaint = "Failed to close the requester for {}".format(settings.BASE_URL)
    assert logged(caplog).count(complaint) == 2
    assert "first-token" not in caplog.text
    assert "second-token" not in caplog.text
    assert thread is not None and not thread.is_alive()


@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
def test_shutdown_stops_the_loop_when_a_close_fails(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))
    stubborn = background_loop.requester_for(make_requester(token="stubborn"))
    working = background_loop.requester_for(make_requester(token="working"))
    background_loop.run(working.request_async, "GET", "courses")
    client = working._client
    thread = background_loop._thread

    async def refuse_to_close() -> None:
        raise OSError("the socket is stuck")

    monkeypatch.setattr(stubborn, "aclose", refuse_to_close)

    with pytest.raises(OSError, match="the socket is stuck"):
        background_loop.shutdown()

    assert client is not None and client.is_closed
    assert thread is not None and not thread.is_alive()


def test_shutdown_from_the_loop_thread_raises() -> None:
    async def shut_down_on_the_loop() -> None:
        background_loop.shutdown()

    with pytest.raises(RuntimeError, match="loop's thread"):
        background_loop.run(shut_down_on_the_loop)

    assert background_loop._portal is not None
    assert background_loop.run(seven) == 7


def test_shutdown_waits_for_a_run_in_flight() -> None:
    started = threading.Event()
    returned: list[int] = []

    async def answer_after_a_pause() -> int:
        started.set()
        await anyio.sleep(0.2)

        return 7

    def call_run() -> None:
        returned.append(background_loop.run(answer_after_a_pause))

    caller = threading.Thread(target=call_run)
    caller.start()
    assert started.wait(10)

    background_loop.shutdown()
    caller.join(10)

    assert returned == [7]


def test_the_portal_refuses_a_run_that_arrives_after_shutdown() -> None:
    """
    The other side of the wait above: a caller that gets there too late.

    A ``run`` that read the portal just before ``shutdown`` stopped it holds
    the object this asks, since ``run`` releases the lock before it calls.
    """
    background_loop.run(seven)
    portal = background_loop._portal
    assert portal is not None

    background_loop.shutdown()

    with pytest.raises(RuntimeError, match="portal is not running"):
        portal.start_task_soon(seven)


@respx.mock(base_url=settings.BASE_URL_WITH_VERSION)
def test_shutdown_leaves_a_loop_that_already_stopped_alone(
    respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    """
    ``shutdown`` reaching a portal that has stopped on its own.

    The portal is stopped through itself while a lingering task holds the
    loop's unwind open, so the module still points at a portal that refuses
    every call when ``shutdown`` reads it. A watching thread releases that
    task once ``shutdown`` has taken the state over, so nothing here waits
    out a duration.
    """
    release = threading.Event()

    async def linger() -> None:
        await to_thread.run_sync(release.wait)

    def release_once_the_state_is_taken() -> None:
        deadline = time.monotonic() + 10
        while background_loop._portal is not None and time.monotonic() < deadline:
            time.sleep(0.005)

        release.set()

    respx_mock.get("courses").mock(return_value=httpx.Response(200, json=[]))
    requester = background_loop.requester_for(make_requester())
    background_loop.run(requester.request_async, "GET", "courses")
    client = requester._client
    portal = background_loop._portal
    thread = background_loop._thread
    assert client is not None and portal is not None and thread is not None

    portal.start_task_soon(linger)
    portal.call(portal.stop)
    watcher = threading.Thread(target=release_once_the_state_is_taken)
    watcher.start()

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        background_loop.shutdown()

    watcher.join(10)

    assert "Background event loop had stopped on its own" in logged(caplog)
    assert not thread.is_alive()
    assert not client.is_closed


def test_a_dying_loop_cancels_the_callers_it_leaves_behind() -> None:
    caught: list[BaseException] = []
    waiting = threading.Event()

    async def wait_a_while() -> None:
        waiting.set()
        await anyio.sleep(30)

    async def leave() -> None:
        raise SystemExit(9)

    def call_run() -> None:
        try:
            background_loop.run(wait_a_while)
        except BaseException as failure:
            caught.append(failure)

    caller = threading.Thread(target=call_run)
    caller.start()
    assert waiting.wait(10)

    with pytest.raises(SystemExit):
        background_loop.run(leave)

    caller.join(10)

    assert len(caught) == 1
    assert isinstance(caught[0], CancelledError)


def test_run_after_shutdown_starts_a_fresh_loop() -> None:
    background_loop.run(seven)
    portal = background_loop._portal
    requester = background_loop.requester_for(make_requester())

    background_loop.shutdown()
    background_loop.run(seven)

    assert background_loop._portal is not portal
    assert background_loop.requester_for(make_requester()) is not requester


def test_concurrent_first_use_starts_one_loop() -> None:
    callers = 24
    together = threading.Barrier(callers)
    seen: list[tuple[int, BlockingPortal | None]] = []

    def call_run() -> None:
        together.wait()
        seen.append((background_loop.run(seven), background_loop._portal))

    threads = [threading.Thread(target=call_run) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [result for result, _ in seen] == [7] * callers
    assert all(portal is background_loop._portal for _, portal in seen)
    assert len(loop_threads()) == 1


def test_run_from_thread_with_running_loop() -> None:
    async def main() -> int:
        return await asyncio.to_thread(background_loop.run, three)

    assert asyncio.run(main()) == 3


def test_run_from_the_loop_thread_raises() -> None:
    async def call_run_on_the_loop() -> int:
        return background_loop.run(seven)

    with pytest.raises(RuntimeError, match="event loop thread"):
        background_loop.run(call_run_on_the_loop)


def test_exception_reaches_the_caller_unchanged() -> None:
    failure = ValueError("the endpoint disagreed")

    async def raise_it() -> None:
        raise failure

    with pytest.raises(ValueError) as caught:
        background_loop.run(raise_it)

    assert caught.value is failure


def test_interrupted_caller_cancels_the_coroutine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A caller that stops waiting takes the coroutine down with it.

    Ctrl-C is reproduced by making the wait itself raise rather than by
    signalling the test process: the future ``run`` waits on gets a ``result``
    that interrupts, while its ``cancel`` stays the real one, so the
    assertion watches the coroutine being cancelled on the loop.
    """
    started = threading.Event()
    cancelled = threading.Event()

    async def wait_to_be_cancelled() -> None:
        started.set()
        try:
            await anyio.sleep(30)
        except anyio.get_cancelled_exc_class():
            cancelled.set()
            raise

    def interrupt_the_wait() -> Any:
        assert started.wait(10)
        raise KeyboardInterrupt

    start_task_soon = BlockingPortal.start_task_soon

    def start_and_interrupt(
        self: BlockingPortal, func: Any, *args: Any, name: Any = None
    ) -> "Future[Any]":
        task = start_task_soon(self, func, *args, name=name)
        task.result = interrupt_the_wait

        return task

    monkeypatch.setattr(BlockingPortal, "start_task_soon", start_and_interrupt)

    with pytest.raises(KeyboardInterrupt):
        background_loop.run(wait_to_be_cancelled)

    assert cancelled.wait(10)


def test_shutdown_in_another_process_leaves_the_loop_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_loop.run(seven)
    portal = background_loop._portal
    thread = background_loop._thread
    assert portal is not None and thread is not None
    monkeypatch.setattr(os, "getpid", lambda: 1)

    background_loop.shutdown()

    assert background_loop._portal is None
    # A stopped portal refuses calls, so a portal that still answers one is a
    # portal shutdown left alone.
    assert portal.call(seven) == 7

    # The loop the module no longer knows about is stopped by hand, since
    # nothing else will, so its thread does not outlive the test.
    portal.call(portal.stop)
    thread.join()


def test_run_after_pid_change_starts_a_fresh_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_loop.run(seven)
    portal = background_loop._portal
    thread = background_loop._thread
    requester = background_loop.requester_for(make_requester())
    assert portal is not None and thread is not None

    monkeypatch.setattr(os, "getpid", lambda: 1)
    background_loop.run(seven)

    assert background_loop._portal is not portal
    assert background_loop.requester_for(make_requester()) is not requester

    # The second loop belongs to the fake pid, so it is stopped while that pid
    # is still in place; the first one is stopped by hand afterwards.
    background_loop.shutdown()
    portal.call(portal.stop)
    thread.join()


def test_a_startup_failure_reaches_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background_loop, "BlockingPortal", no_portal)

    with pytest.raises(RuntimeError, match="no portal today"):
        background_loop.run(seven)

    assert background_loop._portal is None


def test_a_loop_that_dies_is_replaced(caplog: pytest.LogCaptureFixture) -> None:
    """
    A coroutine leaving by a non-Exception tears the loop down with it.

    anyio re-raises such an exception into the portal's task group, so the
    loop ends and the module has to let go of it for the next caller.
    """

    async def leave() -> None:
        raise SystemExit(9)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        with pytest.raises(SystemExit) as caught:
            background_loop.run(leave)

        for thread in loop_threads():
            thread.join(10)

    assert caught.value.code == 9
    assert "Background event loop stopped with an error" in logged(caplog)
    assert background_loop._portal is None
    assert background_loop.run(seven) == 7


def test_blocking_portal_defines_no_finalizer() -> None:
    """Pin the absence the exit paths depend on."""
    assert not hasattr(BlockingPortal, "__del__")


def test_httpx_async_client_defines_no_finalizer() -> None:
    """Pin the absence the exit paths depend on."""
    assert not hasattr(httpx.AsyncClient, "__del__")


@pytest.mark.slow
def test_a_script_that_never_shuts_down_exits_cleanly(tmp_path: Path) -> None:
    finished = run_script(tmp_path, USES_THE_LOOP)

    assert finished.returncode == 0, finished.stderr


@pytest.mark.slow
def test_a_script_exits_cleanly_without_the_exit_handler(tmp_path: Path) -> None:
    source = "import atexit\n{}\natexit.unregister(background_loop.shutdown)\n".format(
        USES_THE_LOOP
    )

    finished = run_script(tmp_path, source)

    assert finished.returncode == 0, finished.stderr


@pytest.mark.slow
def test_a_script_that_raises_exits_with_one(tmp_path: Path) -> None:
    finished = run_script(tmp_path, USES_THE_LOOP + "\nraise RuntimeError('boom')\n")

    assert finished.returncode == 1
    assert "RuntimeError: boom" in finished.stderr


@pytest.mark.slow
def test_a_script_that_exits_keeps_its_status(tmp_path: Path) -> None:
    finished = run_script(tmp_path, USES_THE_LOOP + "\nimport sys\nsys.exit(3)\n")

    assert finished.returncode == 3, finished.stderr


@pytest.mark.slow
def test_a_script_that_exits_from_a_coroutine_keeps_its_status(tmp_path: Path) -> None:
    finished = run_script(tmp_path, LEAVES_BY_SYSTEM_EXIT)

    assert finished.returncode == 9
    # The loop's death is logged, and with logging unconfigured that record
    # lands on stderr. What must not be there is a failure of the exit
    # handler that follows it.
    assert "Background event loop stopped with an error" in finished.stderr
    assert "Exception ignored in atexit callback" not in finished.stderr
    assert "This portal is not running" not in finished.stderr


@pytest.mark.slow
def test_a_script_with_an_open_client_exits_cleanly(tmp_path: Path) -> None:
    finished = run_script(tmp_path, LEAVES_A_CLIENT_OPEN)

    assert finished.returncode == 0, finished.stderr


@pytest.mark.slow
@pytest.mark.skipif(os.name != "posix", reason="requires POSIX signal delivery")
def test_a_ctrl_c_stops_the_request_it_interrupts(tmp_path: Path) -> None:
    finished = run_script(tmp_path, SIGNALS_ITSELF)

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.split() == ["interrupted", "cancelled"]


@pytest.mark.slow
@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_fork_pool_workers_get_their_own_loop(tmp_path: Path) -> None:
    finished = run_script(tmp_path, FORK_POOL)

    assert finished.returncode == 0, finished.stderr
