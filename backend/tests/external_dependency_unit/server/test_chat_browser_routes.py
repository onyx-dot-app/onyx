"""The chat browser's live view websocket against a fake sandbox (faked at
the HarnessSandbox boundary): the starting message, the pump in both
directions, the viewer message size cap, the viewer lease and the close codes. The
owner check runs against Postgres."""

import asyncio
import concurrent.futures
import contextlib
import io
import json
import queue
import threading
from collections.abc import AsyncGenerator, Generator, Iterator
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, UploadFile, WebSocket
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIWebSocketRoute
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from onyx.auth.users import auth_backend, current_user_from_websocket_cookie
from onyx.db.chat import create_chat_session
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.browser_protocol import (
    BrowserFrame,
    FrameKind,
    json_frame,
    parse_json_frame,
)
from onyx.server.features.build.sandbox.harness_base import (
    BrowserStream,
    HarnessSandboxError,
    SandboxFileNotFoundError,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.server.query_and_chat import chat_browser
from onyx.server.settings.models import Settings
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    POSTGRES_DEFAULT_SCHEMA,
)
from tests.external_dependency_unit.conftest import MakeTestUser

JPEG = b"\xff\xd8frame\xff\xd9"


class FakeStream(BrowserStream):
    """The service side of a live view; the test pushes frames (None
    closes) and reads what the route sent."""

    def __init__(self) -> None:
        self.sent: queue.Queue[BrowserFrame] = queue.Queue()
        self.incoming: queue.Queue[BrowserFrame | None] = queue.Queue()
        self.closed = threading.Event()

    async def send(self, frame: BrowserFrame) -> None:
        self.sent.put(frame)

    async def receive(self) -> BrowserFrame | None:
        # The test pushes from its own thread.
        return await asyncio.to_thread(self.incoming.get)

    async def aclose(self) -> None:
        self.closed.set()
        # Ends a receive that still waits.
        self.incoming.put(None)

    def next_sent(self) -> dict[str, JsonValue]:
        return parse_json_frame(self.sent.get(timeout=10))


class FakeSandbox:
    """The HarnessSandbox calls of the live view."""

    def __init__(self) -> None:
        self.stream = FakeStream()
        self.open_error: Exception | None = None
        self.renewed = threading.Event()
        self.opened: list[HarnessSandboxRef] = []
        self.files: dict[str, bytes] = {}
        self.reads: list[tuple[str, int]] = []

    async def open_browser_stream(self, ref: HarnessSandboxRef) -> BrowserStream:
        self.opened.append(ref)
        if self.open_error is not None:
            raise self.open_error
        return self.stream

    def renew_browser_view(self, ref: HarnessSandboxRef) -> None:  # noqa: ARG002
        self.renewed.set()

    def stream_file(
        self,
        ref: HarnessSandboxRef,  # noqa: ARG002
        path: str,
        *,
        max_bytes: int,
    ) -> Iterator[bytes]:
        self.reads.append((path, max_bytes))
        if path not in self.files:
            raise SandboxFileNotFoundError(path)
        data = self.files[path]
        return iter([data[:2], data[2:]])


@pytest.fixture
def ref() -> HarnessSandboxRef:
    return HarnessSandboxRef(
        tenant_id=POSTGRES_DEFAULT_SCHEMA, sandbox_id=uuid4(), session_id=uuid4()
    )


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> FakeSandbox:
    fake = FakeSandbox()
    monkeypatch.setattr(chat_browser, "get_harness_sandbox", lambda: fake)
    return fake


@pytest.fixture
def viewer() -> User:
    return User(id=uuid4(), email="viewer@example.com")


@pytest.fixture
def session_users(
    monkeypatch: pytest.MonkeyPatch, viewer: User
) -> "queue.Queue[User | None]":
    """What each re-read of the viewer's session cookie returns: the queue's
    next item, or the viewer while it is empty."""
    users: queue.Queue[User | None] = queue.Queue()

    async def read_user(websocket: WebSocket) -> User | None:  # noqa: ARG001
        try:
            return users.get_nowait()
        except queue.Empty:
            return viewer

    monkeypatch.setattr(chat_browser, "read_websocket_cookie_user", read_user)
    return users


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    ref: HarnessSandboxRef,
    viewer: User,
    sandbox: FakeSandbox,  # noqa: ARG001
    session_users: "queue.Queue[User | None]",  # noqa: ARG001
) -> Generator[TestClient, None, None]:
    def browser_ref(
        chat_session_id: UUID,
        user: User,  # noqa: ARG001
        *,
        require_setting: bool = True,  # noqa: ARG001
    ) -> HarnessSandboxRef:
        if chat_session_id != ref.session_id:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat session not found.")
        return ref

    monkeypatch.setattr(chat_browser, "_browser_ref", browser_ref)
    monkeypatch.setattr(chat_browser, "_existing_browser_ref", browser_ref)
    app = FastAPI()
    app.include_router(chat_browser.router)

    async def signed_in() -> AsyncGenerator[User, None]:
        yield viewer

    app.dependency_overrides[current_user_from_websocket_cookie] = signed_in
    with TestClient(app) as test_client:
        yield test_client


def _url(chat_session_id: UUID, query: str = "") -> str:
    return f"/chat/sessions/{chat_session_id}/browser/ws{query}"


def test_the_live_view_pumps_frames_and_forwards_viewer_messages(
    client: TestClient, sandbox: FakeSandbox, ref: HarnessSandboxRef
) -> None:
    # TestClient cancels an app that is still cleaning up when the viewer
    # leaves; the route's cleanup runs anyway, as the end of the test checks.
    with (
        contextlib.suppress(concurrent.futures.CancelledError),
        client.websocket_connect(_url(ref.session_id)) as ws,
    ):
        assert ws.receive_json() == {"type": "starting"}
        assert sandbox.stream.next_sent() == {
            "op": "view",
            "chat": str(ref.session_id),
        }

        sandbox.stream.incoming.put(json_frame({"type": "tabs", "tabs": []}))
        assert json.loads(ws.receive_text()) == {"type": "tabs", "tabs": []}
        sandbox.stream.incoming.put(BrowserFrame(kind=FrameKind.JPEG, payload=JPEG))
        assert ws.receive_bytes() == JPEG

        ws.send_text(json.dumps({"type": "takeControl"}))
        assert sandbox.stream.next_sent() == {"type": "takeControl"}

        # The service checks viewer messages; the route only forwards them.
        ws.send_text("not json")
        assert sandbox.stream.sent.get(timeout=10) == BrowserFrame(
            kind=FrameKind.JSON, payload=b"not json"
        )
        # A message over the size cap is dropped.
        ws.send_text("x" * (chat_browser._MAX_VIEWER_MESSAGE_BYTES + 1))
        ws.send_text(json.dumps({"type": "releaseControl"}))
        assert sandbox.stream.next_sent() == {"type": "releaseControl"}

        assert sandbox.renewed.wait(10)
    # The viewer left: the route closes its service connection.
    assert sandbox.stream.closed.wait(10)


def test_a_browser_that_closes_asks_the_viewer_to_reconnect(
    client: TestClient, sandbox: FakeSandbox, ref: HarnessSandboxRef
) -> None:
    with client.websocket_connect(_url(ref.session_id)) as ws:
        assert ws.receive_json() == {"type": "starting"}
        sandbox.stream.incoming.put(None)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_RECONNECT
    assert sandbox.stream.closed.wait(10)


def test_an_unavailable_sandbox_closes_with_4503_after_starting(
    client: TestClient, sandbox: FakeSandbox, ref: HarnessSandboxRef
) -> None:
    sandbox.open_error = HarnessSandboxError("no capacity")
    with client.websocket_connect(_url(ref.session_id)) as ws:
        assert ws.receive_json() == {"type": "starting"}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_UNAVAILABLE
    assert closed.value.reason == "no capacity"


def test_turning_the_browser_off_closes_an_open_view(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    sandbox: FakeSandbox,
    ref: HarnessSandboxRef,
) -> None:
    monkeypatch.setattr(chat_browser, "_VIEW_RENEW_SECONDS", 0.05)
    turned_off = threading.Event()

    def browser_ref(
        chat_session_id: UUID,  # noqa: ARG001
        user: User,  # noqa: ARG001
        *,
        require_setting: bool = True,  # noqa: ARG001
    ) -> HarnessSandboxRef:
        if turned_off.is_set():
            raise OnyxError(
                OnyxErrorCode.FEATURE_DISABLED, "The browser is turned off."
            )
        return ref

    monkeypatch.setattr(chat_browser, "_browser_ref", browser_ref)
    with client.websocket_connect(_url(ref.session_id)) as ws:
        assert ws.receive_json() == {"type": "starting"}
        assert sandbox.stream.next_sent()["op"] == "view"
        turned_off.set()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_FORBIDDEN
    assert sandbox.stream.closed.wait(10)


def test_a_view_closes_when_the_viewers_session_ends(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    sandbox: FakeSandbox,
    ref: HarnessSandboxRef,
    session_users: "queue.Queue[User | None]",
) -> None:
    """A logout, a deactivation or a lost permission ends the view at the
    next renewal."""
    monkeypatch.setattr(chat_browser, "_VIEW_RENEW_SECONDS", 0.05)
    with client.websocket_connect(_url(ref.session_id)) as ws:
        assert ws.receive_json() == {"type": "starting"}
        assert sandbox.stream.next_sent()["op"] == "view"
        session_users.put(None)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_FORBIDDEN
    assert sandbox.stream.closed.wait(10)


def test_a_check_that_cannot_complete_asks_the_viewer_to_reconnect(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    sandbox: FakeSandbox,
    ref: HarnessSandboxRef,
) -> None:
    """The reconnect checks access again before a new view opens."""
    monkeypatch.setattr(chat_browser, "_VIEW_RENEW_SECONDS", 0.05)
    broken = threading.Event()

    def browser_ref(
        chat_session_id: UUID,  # noqa: ARG001
        user: User,  # noqa: ARG001
        *,
        require_setting: bool = True,  # noqa: ARG001
    ) -> HarnessSandboxRef:
        if broken.is_set():
            raise RuntimeError("database down")
        return ref

    monkeypatch.setattr(chat_browser, "_browser_ref", browser_ref)
    with client.websocket_connect(_url(ref.session_id)) as ws:
        assert ws.receive_json() == {"type": "starting"}
        assert sandbox.stream.next_sent()["op"] == "view"
        broken.set()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_RECONNECT
    assert sandbox.stream.closed.wait(10)


def test_a_first_check_that_cannot_complete_asks_the_viewer_to_reconnect(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, sandbox: FakeSandbox
) -> None:
    def browser_ref(
        chat_session_id: UUID,  # noqa: ARG001
        user: User,  # noqa: ARG001
        *,
        require_setting: bool = True,  # noqa: ARG001
    ) -> HarnessSandboxRef:
        raise RuntimeError("database down")

    monkeypatch.setattr(chat_browser, "_browser_ref", browser_ref)
    with client.websocket_connect(_url(uuid4())) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_RECONNECT
    assert sandbox.opened == []


def test_a_cancelled_pump_cancels_and_awaits_its_pumps() -> None:
    """The route's task can be cancelled (the server shuts down) while the
    pump waits; no pump task outlives it."""
    pumps_ended = asyncio.Event()
    receiving = asyncio.Event()

    class IdleStream(FakeStream):
        async def receive(self) -> BrowserFrame | None:
            receiving.set()
            try:
                await asyncio.Event().wait()
            finally:
                pumps_ended.set()
            return None

    class IdleWebSocket:
        async def receive(self) -> dict[str, str]:
            await asyncio.Event().wait()
            return {"type": "websocket.disconnect"}

    async def lease_never_ends() -> OnyxError:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def run() -> None:
        lease = asyncio.create_task(lease_never_ends())
        pump = asyncio.create_task(
            chat_browser._pump(
                IdleWebSocket(),  # ty: ignore[invalid-argument-type]
                IdleStream(),
                uuid4(),
                lease,
            )
        )
        await receiving.wait()
        pump.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pump
        assert pumps_ended.is_set()
        lease.cancel()

    asyncio.run(run())


def test_a_download_returns_the_file_as_an_attachment(
    client: TestClient,  # noqa: ARG001 - patches _browser_ref
    sandbox: FakeSandbox,
    ref: HarnessSandboxRef,
    viewer: User,
) -> None:
    sandbox.files["downloads/report (1).pdf"] = b"%PDF"

    response = chat_browser.download_chat_browser_file(
        ref.session_id, "report (1).pdf", viewer
    )

    async def body() -> bytes:
        chunks = [chunk async for chunk in response.body_iterator]
        if not all(isinstance(chunk, bytes) for chunk in chunks):
            raise TypeError("the download streams bytes")
        return b"".join(chunk for chunk in chunks if isinstance(chunk, bytes))

    assert asyncio.run(body()) == b"%PDF"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "report%20%281%29.pdf" in response.headers["content-disposition"]
    assert sandbox.reads == [
        ("downloads/report (1).pdf", chat_browser.BROWSER_DOWNLOAD_MAX_BYTES)
    ]


@pytest.mark.parametrize("name", ["..", ".", "a/b.pdf", "a\\b.pdf", "a\x00b", ""])
def test_a_download_takes_only_a_plain_file_name(
    client: TestClient,  # noqa: ARG001 - patches _browser_ref
    sandbox: FakeSandbox,
    ref: HarnessSandboxRef,
    viewer: User,
    name: str,
) -> None:
    with pytest.raises(OnyxError) as refused:
        chat_browser.download_chat_browser_file(ref.session_id, name, viewer)
    assert refused.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert sandbox.reads == []


def test_a_missing_download_or_another_users_chat_is_not_found(
    client: TestClient,  # noqa: ARG001 - patches _browser_ref
    sandbox: FakeSandbox,
    ref: HarnessSandboxRef,
    viewer: User,
) -> None:
    with pytest.raises(OnyxError) as refused:
        chat_browser.download_chat_browser_file(ref.session_id, "gone.pdf", viewer)
    assert refused.value.error_code is OnyxErrorCode.NOT_FOUND

    sandbox.files["downloads/report.pdf"] = b"%PDF"
    with pytest.raises(OnyxError) as refused:
        chat_browser.download_chat_browser_file(uuid4(), "report.pdf", viewer)
    assert refused.value.error_code is OnyxErrorCode.NOT_FOUND
    assert sandbox.reads == [
        ("downloads/gone.pdf", chat_browser.BROWSER_DOWNLOAD_MAX_BYTES)
    ]


def test_an_upload_to_another_users_chat_is_refused_before_its_size_checks(
    client: TestClient,  # noqa: ARG001 - patches _browser_ref
) -> None:
    """The ownership check runs first, so a non-owner learns nothing from
    the size checks."""
    files = [
        UploadFile(io.BytesIO(b"x"), size=1, filename=f"f{i}.txt")
        for i in range(chat_browser.BROWSER_UPLOAD_MAX_FILES + 1)
    ]
    with pytest.raises(OnyxError) as refused:
        chat_browser.upload_chat_browser_files(
            uuid4(), files, User(id=uuid4(), email="viewer@example.com")
        )
    assert refused.value.error_code is OnyxErrorCode.NOT_FOUND


def test_an_unknown_chat_closes_with_4404(
    client: TestClient, sandbox: FakeSandbox
) -> None:
    with client.websocket_connect(_url(uuid4())) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == chat_browser.CLOSE_NOT_FOUND
    assert sandbox.opened == []


def test_the_owner_check_and_the_setting_gate_the_browser(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    make_test_user: MakeTestUser,
) -> None:
    owner = make_test_user("browser_owner")
    other = make_test_user("browser_other")
    chat_session = create_chat_session(
        db_session, description=None, user_id=owner.id, persona_id=None
    )
    monkeypatch.setattr(chat_browser, "HARNESS_SANDBOX_ENABLED", True)
    settings = Settings()
    monkeypatch.setattr(
        chat_browser, "load_browser_enabled", lambda: settings.browser_enabled
    )

    # A read finds no sandbox before the first use creates it.
    with pytest.raises(OnyxError) as refused:
        chat_browser._existing_browser_ref(chat_session.id, owner)
    assert refused.value.error_code is OnyxErrorCode.NOT_FOUND
    ref = chat_browser._browser_ref(chat_session.id, owner)
    assert ref.session_id == chat_session.id
    assert ref.tenant_id == CURRENT_TENANT_ID_CONTEXTVAR.get()
    # The same sandbox on each call.
    assert chat_browser._browser_ref(chat_session.id, owner) == ref
    assert chat_browser._existing_browser_ref(chat_session.id, owner) == ref
    with pytest.raises(OnyxError) as refused:
        chat_browser._existing_browser_ref(chat_session.id, other)
    assert refused.value.error_code is OnyxErrorCode.NOT_FOUND

    with pytest.raises(OnyxError) as refused:
        chat_browser._browser_ref(chat_session.id, other)
    assert refused.value.error_code is OnyxErrorCode.NOT_FOUND

    incognito_chat = create_chat_session(
        db_session,
        description=None,
        user_id=owner.id,
        persona_id=None,
        incognito_record_mode=IncognitoRecordMode.USAGE_ONLY,
    )
    with pytest.raises(OnyxError) as refused:
        chat_browser._browser_ref(incognito_chat.id, owner)
    assert refused.value.error_code is OnyxErrorCode.FEATURE_DISABLED

    settings.browser_enabled = False
    with pytest.raises(OnyxError) as refused:
        chat_browser._browser_ref(chat_session.id, owner)
    assert refused.value.error_code is OnyxErrorCode.FEATURE_DISABLED
    # "Clear browser data" still deletes saved sign-ins, for the owner only.
    cleared: list[HarnessSandboxRef] = []
    monkeypatch.setattr(
        chat_browser,
        "get_harness_sandbox",
        lambda: SimpleNamespace(clear_browser_data=cleared.append),
    )
    chat_browser.clear_chat_browser_data(chat_session.id, owner)
    assert cleared == [ref]
    for chat_id, user in ((chat_session.id, other), (incognito_chat.id, owner)):
        with pytest.raises(OnyxError):
            chat_browser.clear_chat_browser_data(chat_id, user)
    assert cleared == [ref]

    settings.browser_enabled = True
    monkeypatch.setattr(chat_browser, "HARNESS_SANDBOX_ENABLED", False)
    with pytest.raises(OnyxError) as refused:
        chat_browser._browser_ref(chat_session.id, owner)
    assert refused.value.error_code is OnyxErrorCode.FEATURE_DISABLED


def test_the_live_view_holds_no_auth_strategy_for_its_life() -> None:
    """A strategy dependency lives as long as the websocket, and Postgres
    auth's strategy holds a DB session; each check builds its own instead."""
    route = next(
        r
        for r in chat_browser.router.routes
        if isinstance(r, APIWebSocketRoute) and r.path.endswith("/browser/ws")
    )

    def calls(dependant: Dependant) -> list[object]:
        found: list[object] = []
        for sub in dependant.dependencies:
            found.append(sub.call)
            found += calls(sub)
        return found

    assert auth_backend.get_strategy not in calls(route.dependant)
