"""The browser of FirecrackerHarnessSandbox against Redis, a fake host agent
and a fake browser service (a TCP server in the service's framing behind the
fake agent's Dial): agent calls, the live view stream, the profile save on a
stop, and "clear browser data"."""

import asyncio
import io
import socket
import socketserver
import threading
import time
import zipfile
from collections.abc import Generator
from uuid import UUID, uuid4

import grpc
import pytest
from pydantic import JsonValue

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend, CacheLock
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
)
from onyx.microvm import registry
from onyx.microvm.browser_protocol import (
    BROWSER_SERVICE_PORT,
    MAX_FRAME_BYTES,
    BrowserFrame,
    BrowserFramingError,
    FrameDecoder,
    FrameKind,
    encode_frame,
    json_frame,
    parse_json_frame,
    view_hello,
)
from onyx.microvm.daemon_client import SandboxDaemonClient
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    VmStopOutcome,
    evict_idle_sandbox_vm,
)
from onyx.microvm.models import PlacedVm
from onyx.microvm.registry import get_sandbox_placement
from onyx.server.features.build.sandbox.firecracker import (
    harness_sandbox,
    harness_state,
)
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    session_save_lock,
)
from onyx.server.features.build.sandbox.harness_base import HarnessSandboxError
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)
from tests.external_dependency_unit.microvm.test_firecracker_session_saves import (
    FakeArchiveStore,
)

JPEG = b"\xff\xd8\xff\xe0frame\xff\xd9"


class FakeBrowserService:
    """The guest's browser service: answers an agent call with `answer` (or
    sends `raw_answer`), and streams a view: a tabs message and a JPEG
    frame, then an echo of each viewer message."""

    def __init__(self) -> None:
        self.hellos: list[dict[str, JsonValue]] = []
        self.viewer_messages: list[dict[str, JsonValue]] = []
        self.answer: dict[str, JsonValue] = {"ok": True, "result": {"tab": "t1"}}
        self.raw_answer: bytes | None = None
        # A call waits for this before it answers.
        self.release = threading.Event()
        self.release.set()
        self.called = threading.Event()
        self.closed_views = threading.Event()
        self._connections: list[socket.socket] = []
        service = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                service._serve(self.request)

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.server.server_address[:2]
        return str(host), int(port)

    def stop(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        for conn in self._connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _serve(self, conn: socket.socket) -> None:
        self._connections.append(conn)
        decoder = FrameDecoder()
        frames: list[BrowserFrame] = []
        while not frames:
            data = conn.recv(65536)
            if not data:
                return
            frames = decoder.feed(data)
        hello = parse_json_frame(frames.pop(0))
        self.hellos.append(hello)
        if hello["op"] == "call":
            self.called.set()
            self.release.wait(10)
            conn.sendall(
                self.raw_answer
                if self.raw_answer is not None
                else encode_frame(json_frame(self.answer))
            )
            return
        conn.sendall(encode_frame(json_frame({"type": "tabs", "tabs": []})))
        conn.sendall(encode_frame(BrowserFrame(kind=FrameKind.JPEG, payload=JPEG)))
        try:
            while True:
                for frame in frames:
                    message = parse_json_frame(frame)
                    self.viewer_messages.append(message)
                    conn.sendall(
                        encode_frame(json_frame({"type": "echo", "message": message}))
                    )
                data = conn.recv(65536)
                if not data:
                    return
                frames = decoder.feed(data)
        except OSError:
            return
        finally:
            self.closed_views.set()


@pytest.fixture
def node(add_node: AddNode) -> RunningFakeAgent:
    return add_node(f"fcb-{uuid4().hex[:6]}")


@pytest.fixture
def store(node: RunningFakeAgent) -> FakeArchiveStore:
    return FakeArchiveStore(node)


@pytest.fixture
def sandbox(
    client_factory: InsecureClientFactory, store: FakeArchiveStore
) -> FirecrackerHarnessSandbox:
    return FirecrackerHarnessSandbox(
        template="tpl-1",
        client_factory=client_factory,
        archive_store=store,
        turn_end_save_interval_seconds=0,
    )


@pytest.fixture
def ref(
    tenant_cache: CacheBackend, new_sandbox_id: NewSandboxId
) -> Generator[HarnessSandboxRef, None, None]:
    ref = HarnessSandboxRef(
        tenant_id=TENANT_ID, sandbox_id=new_sandbox_id(), session_id=uuid4()
    )
    yield ref
    for prefix in (
        harness_state.EXEC_SESSIONS_PREFIX,
        harness_state.ACTIVITY_PREFIX,
        harness_state.SESSION_INSTANCES_PREFIX,
        harness_state.LAST_ATTEMPT_PREFIX,
        harness_state.SAVED_SESSIONS_PREFIX,
        harness_state.WANTED_PREFIX,
        harness_state.PURGED_SANDBOX_PREFIX,
    ):
        tenant_cache.delete(prefix + str(ref.sandbox_id))
    for session_id in (ref.session_id, ref.sandbox_id):
        for prefix in (
            harness_state.SESSION_SAVE_PREFIX,
            harness_state.PURGED_SESSION_PREFIX,
        ):
            tenant_cache.delete(prefix + str(session_id))


@pytest.fixture
def service(
    node: RunningFakeAgent, ref: HarnessSandboxRef
) -> Generator[FakeBrowserService, None, None]:
    service = FakeBrowserService()
    node.agent.dial_targets[(str(ref.sandbox_id), BROWSER_SERVICE_PORT)] = (
        service.address
    )
    yield service
    service.stop()


def _sleep(sandbox: FirecrackerHarnessSandbox, ref: HarnessSandboxRef) -> VmStopOutcome:
    """The idle stop of the sandbox now, as if it were idle long enough."""
    tenant_cache = get_cache_backend(tenant_id=TENANT_ID)
    tenant_cache.delete(harness_state.WANTED_PREFIX + str(ref.sandbox_id))
    return evict_idle_sandbox_vm(
        get_shared_cache_backend(),
        tenant_cache,
        sandbox._client_factory,
        sandbox.session_checkpointer() or NoCheckpointSupport(),
        sandbox,
        tenant_id=TENANT_ID,
        sandbox_id=ref.sandbox_id,
        last_active=0,
        now=int(time.time()),
    )


def _saved_profile(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> str:
    """Start the browser, give its profile a cookie and stop the VM; returns
    the file ID of the profile's save."""
    sid = str(ref.sandbox_id)
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    node.agent.files[(sid, sid, "chrome/Default/Cookies")] = b"x"
    assert _sleep(sandbox, ref) is VmStopOutcome.STOPPED
    save = harness_state.get_session_save(tenant_cache, ref.sandbox_id)
    assert save is not None and save.file_id is not None
    return save.file_id


def test_frame_decoder_splits_a_stream_and_rejects_bad_lengths() -> None:
    first = json_frame({"op": "view"})
    second = BrowserFrame(kind=FrameKind.JPEG, payload=JPEG)
    data = encode_frame(first) + encode_frame(second)
    decoder = FrameDecoder()
    frames = [frame for byte in data for frame in decoder.feed(bytes([byte]))]
    assert frames == [first, second]
    assert decoder.pending_bytes == 0

    with pytest.raises(BrowserFramingError):
        FrameDecoder().feed((MAX_FRAME_BYTES + 1).to_bytes(4, "big") + b"\x01")
    with pytest.raises(BrowserFramingError):
        FrameDecoder().feed(b"\x00\x00\x00\x00")
    with pytest.raises(BrowserFramingError):
        FrameDecoder().feed(b"\x00\x00\x00\x02\x07x")
    with pytest.raises(BrowserFramingError):
        parse_json_frame(BrowserFrame(kind=FrameKind.JSON, payload=b"[1]"))


def test_a_call_restores_the_profile_starts_the_browser_and_returns_the_result(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    service: FakeBrowserService,
    ref: HarnessSandboxRef,
) -> None:
    result = sandbox.browser_call(
        ref, "open", {"url": "example.com"}, timeout_seconds=10
    )

    assert result == {"tab": "t1"}
    assert service.hellos == [
        {
            "op": "call",
            "chat": str(ref.session_id),
            "method": "open",
            "params": {"url": "example.com"},
        }
    ]
    assert node.agent.events == [f"browser_start:{ref.sandbox_id}"]
    placement = harness_state.sessions_on_instance(
        tenant_cache,
        ref.sandbox_id,
        next(
            (vm.attempt, vm.generation)
            for vm in node.agent.vms.values()
            if vm.sandbox_id == str(ref.sandbox_id)
        ),
    )
    # The profile session is set up on the instance, so a stop saves it.
    assert ref.sandbox_id in placement


def test_a_call_fails_when_the_vm_instance_changes_during_setup(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    service: FakeBrowserService,
    ref: HarnessSandboxRef,
) -> None:
    """The chat session is set up on the instance that serves the call, or
    the call fails: its downloads go to the chat session directory."""
    session_vm = sandbox._session_vm

    def next_instance_for_the_profile(
        r: HarnessSandboxRef,
    ) -> tuple[PlacedVm, SandboxDaemonClient]:
        placed, daemon = session_vm(r)
        if r.session_id != ref.sandbox_id:
            return placed, daemon
        vm = placed.vm.model_copy(update={"generation": placed.vm.generation + 1})
        return placed.model_copy(update={"vm": vm}), daemon

    monkeypatch.setattr(sandbox, "_session_vm", next_instance_for_the_profile)

    with pytest.raises(HarnessSandboxError, match="restarted"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    assert node.agent.events == []
    assert service.hellos == []


def test_a_refused_call_raises_the_service_message(
    sandbox: FirecrackerHarnessSandbox,
    service: FakeBrowserService,
    ref: HarnessSandboxRef,
) -> None:
    message = (
        "A human controls this tab. Open a new tab with "
        "browser_open(new_tab=true) to keep working, or ask the user to "
        "release control."
    )
    service.answer = {
        "ok": False,
        "error": {"code": "human_control", "message": message},
    }

    with pytest.raises(HarnessSandboxError) as raised:
        sandbox.browser_call(ref, "act", {"action": "click"}, timeout_seconds=10)
    assert str(raised.value) == message


def test_bad_answers_and_an_unreachable_browser_raise_sandbox_errors(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    service: FakeBrowserService,
    ref: HarnessSandboxRef,
) -> None:
    service.raw_answer = (MAX_FRAME_BYTES + 1).to_bytes(4, "big")
    with pytest.raises(HarnessSandboxError, match="bad answer"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=10)

    service.raw_answer = b""
    with pytest.raises(HarnessSandboxError, match="without an answer"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=10)

    service.release.clear()
    service.raw_answer = None
    with pytest.raises(HarnessSandboxError, match="did not answer within 1"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=1)
    service.release.set()

    del node.agent.dial_targets[(str(ref.sandbox_id), BROWSER_SERVICE_PORT)]
    with pytest.raises(HarnessSandboxError, match="Could not reach the browser"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=10)

    node.agent.browser_start_error = grpc.StatusCode.UNIMPLEMENTED
    with pytest.raises(HarnessSandboxError, match="older image"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=10)

    node.agent.browser_start_error = None
    node.agent.browser_service_protocol = 0
    with pytest.raises(HarnessSandboxError, match="older image"):
        sandbox.browser_call(ref, "status", {}, timeout_seconds=10)


def test_a_stop_cancels_a_call_in_progress(
    sandbox: FirecrackerHarnessSandbox,
    service: FakeBrowserService,
    ref: HarnessSandboxRef,
) -> None:
    service.release.clear()
    signal = CancellationSignal()

    def cancel_once_called() -> None:
        # Cancel only while the reply wait blocks, not during VM setup.
        if service.called.wait(10):
            signal.cancel()

    threading.Thread(target=cancel_once_called, daemon=True).start()
    started = time.monotonic()
    try:
        with cancellation_scope(signal), pytest.raises(AgentCancelled):
            sandbox.browser_call(ref, "status", {}, timeout_seconds=30)
    finally:
        service.release.set()
    assert time.monotonic() - started < 10


def test_the_live_view_streams_frames_both_ways(
    sandbox: FirecrackerHarnessSandbox,
    service: FakeBrowserService,
    ref: HarnessSandboxRef,
) -> None:
    async def view() -> list[BrowserFrame]:
        stream = await sandbox.open_browser_stream(ref)
        try:
            await stream.send(view_hello(str(ref.session_id)))
            await stream.send(json_frame({"type": "takeControl"}))
            frames = []
            for _ in range(3):
                frame = await stream.receive()
                assert frame is not None
                frames.append(frame)
            return frames
        finally:
            await stream.aclose()

    frames = asyncio.run(view())

    assert [frame.kind for frame in frames] == [
        FrameKind.JSON,
        FrameKind.JPEG,
        FrameKind.JSON,
    ]
    assert frames[1].payload == JPEG
    assert parse_json_frame(frames[2]) == {
        "type": "echo",
        "message": {"type": "takeControl"},
    }
    assert service.hellos[0]["op"] == "view"
    assert service.hellos[0]["chat"] == str(ref.session_id)
    # Closing the stream closes the service's connection.
    assert service.closed_views.wait(10)


def test_an_open_live_view_keeps_the_vm(
    sandbox: FirecrackerHarnessSandbox,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    sandbox.renew_browser_view(ref)
    assert sandbox.is_busy(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)
    assert _sleep(sandbox, ref) is VmStopOutcome.KEPT_BUSY


def test_a_stop_closes_chrome_before_it_saves_the_profile_without_caches(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    store: FakeArchiveStore,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    # The profile is the session named by the sandbox ID.
    sid = profile = str(ref.sandbox_id)
    for path in (
        "chrome/Default/Cookies",
        "chrome/Default/Cache/Cache_Data/data_0",
        "chrome/Default/Code Cache/js/index",
        "chrome/Default/Service Worker/CacheStorage/abc/index",
        "chrome/Default/Service Worker/Database/MANIFEST",
        "chrome/GrShaderCache/data_1",
        "chrome/Crashpad/settings.dat",
        "chrome/SingletonLock",
    ):
        node.agent.files[(sid, profile, path)] = b"x"

    assert _sleep(sandbox, ref) is VmStopOutcome.STOPPED

    events = node.agent.events
    assert events.index("browser_stop") < events.index(f"capture:{profile}")
    save = harness_state.get_session_save(tenant_cache, ref.sandbox_id)
    assert save is not None and save.file_id is not None
    with zipfile.ZipFile(io.BytesIO(node.agent.objects[save.file_id])) as archive:
        assert sorted(archive.namelist()) == [
            "chrome/Default/Cookies",
            "chrome/Default/Service Worker/Database/MANIFEST",
        ]

    # The next VM gets the profile back before the browser starts.
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    assert node.agent.files[(sid, profile, "chrome/Default/Cookies")] == b"x"
    assert store.downloads == 1


def test_a_stop_that_a_call_cancels_starts_chrome_again(
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    """The VM stays, so its browser runs again as before the stop."""
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    sandbox.write_file(ref, "notes.txt", b"a")
    node.agent.capture_delay_seconds = 30.0
    outcome: list[VmStopOutcome] = []
    stop = threading.Thread(target=lambda: outcome.append(_sleep(sandbox, ref)))
    stop.start()
    try:
        assert node.agent.capture_started.wait(timeout=10)
        assert sandbox.read_file(ref, "notes.txt", max_bytes=10) == b"a"
    finally:
        # A wanted sandbox cancels the delayed capture, so the stop ends.
        harness_state.note_wanted(
            get_cache_backend(tenant_id=TENANT_ID), ref.sandbox_id
        )
        stop.join(timeout=40)
    assert not stop.is_alive()

    assert outcome == [VmStopOutcome.KEPT_NO_CHECKPOINT]
    events = node.agent.events
    assert f"browser_start:{ref.sandbox_id}" in events[events.index("browser_stop") :]


def test_a_browser_call_sets_up_the_chat_session_so_its_downloads_are_saved(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    store: FakeArchiveStore,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    """A browser call before any sandbox tool: the chat's downloads still
    get saved at the stop and come back on the next VM."""
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    sid, chat = str(ref.sandbox_id), str(ref.session_id)
    node.agent.files[(sid, chat, "downloads/report.pdf")] = b"pdf"

    assert _sleep(sandbox, ref) is VmStopOutcome.STOPPED

    save = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert save is not None and save.file_id is not None
    with zipfile.ZipFile(io.BytesIO(node.agent.objects[save.file_id])) as archive:
        assert archive.namelist() == ["downloads/report.pdf"]

    # The next VM restores the chat's save (the empty profile has no file).
    profile_save = harness_state.get_session_save(tenant_cache, ref.sandbox_id)
    assert profile_save is not None and profile_save.file_id is None
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    assert store.downloads == 1


def test_a_stop_does_not_save_browser_uploads(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    ref: HarnessSandboxRef,
) -> None:
    """Uploads for the file chooser can reach 2 GiB, over the 1 GiB archive
    limit; a save that fails keeps the VM from ever stopping."""
    sandbox.write_file(ref, "browser-uploads/ab12cd34/video.mp4", b"x")
    sandbox.write_file(ref, "notes.txt", b"y")

    assert _sleep(sandbox, ref) is VmStopOutcome.STOPPED

    save = harness_state.get_session_save(tenant_cache, ref.session_id)
    assert save is not None and save.file_id is not None
    with zipfile.ZipFile(io.BytesIO(node.agent.objects[save.file_id])) as archive:
        assert archive.namelist() == [".onyx-top-level/notes.txt"]


def test_clear_browser_data_stops_chrome_and_deletes_the_profile_and_its_save(
    monkeypatch: pytest.MonkeyPatch,
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    store: FakeArchiveStore,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    sid = str(ref.sandbox_id)
    file_id = _saved_profile(tenant_cache, sandbox, node, ref)
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    assert (sid, sid, "chrome/Default/Cookies") in node.agent.files
    node.agent.events.clear()

    # A save of the profile in progress refuses the clear.
    with session_save_lock(tenant_cache, ref.sandbox_id) as held:
        assert held
        with pytest.raises(HarnessSandboxError, match="being saved"):
            sandbox.clear_browser_data(ref)

    # The viewer reconnects as soon as the clear stops Chrome. That call must
    # neither restore the old save nor start Chrome on the old profile before
    # the clear ends.
    racers: list[threading.Thread] = []
    outcomes: list[dict[str, JsonValue] | BaseException] = []
    at_profile_lock = threading.Event()
    setup_lock = harness_sandbox._session_setup_lock

    def signalling_setup_lock(
        cache: CacheBackend, sandbox_id: UUID, session_id: UUID
    ) -> CacheLock:
        if session_id == ref.sandbox_id and racers:
            at_profile_lock.set()
        return setup_lock(cache, sandbox_id, session_id)

    monkeypatch.setattr(harness_sandbox, "_session_setup_lock", signalling_setup_lock)

    def call() -> None:
        try:
            outcomes.append(sandbox.browser_call(ref, "status", {}, timeout_seconds=10))
        except BaseException as e:
            outcomes.append(e)

    delete = store.delete

    def delete_during_a_call(deleted_id: str) -> None:
        racer = threading.Thread(target=call)
        racers.append(racer)
        racer.start()
        assert at_profile_lock.wait(10)
        assert f"browser_start:{sid}" not in node.agent.events
        delete(deleted_id)

    store.delete = delete_during_a_call  # ty: ignore[invalid-assignment]

    sandbox.clear_browser_data(ref)

    racers[0].join(10)
    assert not racers[0].is_alive()
    assert outcomes == [{"tab": "t1"}]
    assert node.agent.events == ["browser_stop", f"browser_start:{sid}"]
    assert not [key for key in node.agent.files if key[:2] == (sid, sid)]
    assert harness_state.get_session_save(tenant_cache, ref.sandbox_id) is None
    assert store.deleted == [file_id]
    assert store.downloads == 1


def test_clear_browser_data_on_an_unregistered_node_drops_its_placement(
    tenant_cache: CacheBackend,
    shared_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    """The clear cannot reach the VM. If its node comes back, the old VM
    with the old profile must not serve the browser again: the next wake
    starts a new attempt, and the node's next report stops the old VM."""
    sid = str(ref.sandbox_id)
    sandbox.browser_call(ref, "status", {}, timeout_seconds=10)
    node.agent.files[(sid, sid, "chrome/Default/Cookies")] = b"x"
    placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
    assert placement is not None
    shared_cache.delete(registry._NODE_ADDRESS_PREFIX + placement.node_id)

    sandbox.clear_browser_data(ref)

    assert get_sandbox_placement(tenant_cache, ref.sandbox_id) is None
    assert harness_state.last_attempt(tenant_cache, ref.sandbox_id) >= (
        placement.attempt
    )


def test_sandbox_purge_deletes_the_profile_save(
    tenant_cache: CacheBackend,
    sandbox: FirecrackerHarnessSandbox,
    node: RunningFakeAgent,
    store: FakeArchiveStore,
    service: FakeBrowserService,  # noqa: ARG001
    ref: HarnessSandboxRef,
) -> None:
    sid = str(ref.sandbox_id)
    file_id = _saved_profile(tenant_cache, sandbox, node, ref)
    # A save that the saved-session index lost is found by the sandbox ID.
    harness_state.remove_id(
        tenant_cache, harness_state.SAVED_SESSIONS_PREFIX, ref.sandbox_id, sid
    )

    sandbox.purge_sandbox(tenant_id=TENANT_ID, sandbox_id=ref.sandbox_id)

    assert store.deleted == [file_id]
    assert harness_state.get_session_save(tenant_cache, ref.sandbox_id) is None
