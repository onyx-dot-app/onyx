"""The chat browser's routes: the live view of a chat's tabs (a websocket
pumped to the browser service in the user's sandbox VM), file uploads for
its file chooser, downloads of the files that it saved, and "clear browser
data". Only the chat's owner reaches
them, and only while harness sandboxes run and the `browser_enabled` setting
is on ("clear browser data" also works while the setting is off).

Live view protocol (the service's frames, `onyx.microvm.browser_protocol`):
the route sends the service its view hello for the chat, then forwards each
service JSON message as a text message and each JPEG frame as a binary
message, and each viewer text message (up to 1 MiB; a larger one is
dropped) as a JSON message, which the service checks. Before the VM answers
it sends `{"type": "starting"}`.
Close codes: 4403 forbidden or turned off, 4404 unknown chat, 4503 the
sandbox or its browser did not open. The view checks the session cookie,
the user, the setting and the chat again after each lease renewal, and
closes with 4403 or 4404 on a change, or with 1012 when a check cannot
complete. A view that drops after it opened (the VM, the service or this
server went away) closes with 1012, which the viewer retries.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Final
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketState

from onyx.auth.permissions import require_permission
from onyx.auth.users import (
    current_user_from_websocket_cookie,
    read_websocket_cookie_user,
)
from onyx.db.chat import get_owned_chat_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.sandbox import get_or_create_sandbox, get_sandbox_id_by_user_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.serving import build_content_disposition
from onyx.microvm.agent_client import HostAgentError
from onyx.microvm.browser_protocol import (
    BrowserFrame,
    FrameKind,
    view_hello,
)
from onyx.microvm.configs import HARNESS_SANDBOX_ENABLED
from onyx.microvm.daemon_client import SandboxDaemonError
from onyx.server.features.build.sandbox.harness_base import (
    BROWSER_UPLOADS_DIR,
    BROWSER_VIEW_LEASE_SECONDS,
    BrowserStream,
    HarnessSandbox,
    HarnessSandboxError,
    SandboxFileNotFoundError,
    SandboxFileTooLargeError,
    safe_file_name,
)
from onyx.server.features.build.sandbox.harness_factory import get_harness_sandbox
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.server.query_and_chat.models import BrowserUploadResponse
from onyx.server.settings.store import load_browser_enabled
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/chat")

CLOSE_FORBIDDEN: Final = 4403
CLOSE_NOT_FOUND: Final = 4404
CLOSE_UNAVAILABLE: Final = 4503
# Standard "service restart": the viewer reconnects.
CLOSE_RECONNECT: Final = 1012
# The viewer lease is renewed this often while the live view is open.
_VIEW_RENEW_SECONDS = BROWSER_VIEW_LEASE_SECONDS / 3
# Largest viewer message, in UTF-8 bytes.
_MAX_VIEWER_MESSAGE_BYTES = 1 << 20
_UNAVAILABLE = "The browser is not available."
# A websocket close reason is at most 123 bytes.
_MAX_CLOSE_REASON_BYTES = 123
BROWSER_UPLOAD_MAX_FILES = 20
BROWSER_UPLOAD_MAX_BYTES = 100 << 20
_UPLOAD_TIMEOUT_SECONDS = 600.0
# The browser saves downloads in this directory of the chat session
# directory, up to this many bytes per chat (the browser service's budget).
BROWSER_DOWNLOADS_DIR = "downloads"
BROWSER_DOWNLOAD_MAX_BYTES = 256 << 20
_MAX_DOWNLOAD_NAME_BYTES = 255


@contextmanager
def _sandbox_errors_as_onyx_errors() -> Iterator[None]:
    """Raises a sandbox, host agent or guest daemon failure as
    SERVICE_UNAVAILABLE."""
    try:
        yield
    except (HarnessSandboxError, HostAgentError, SandboxDaemonError) as e:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE, str(e)) from e


def _check_browser_chat(
    chat_session_id: UUID,
    user: User,
    db_session: Session,
    *,
    require_setting: bool = True,
) -> None:
    """Raises OnyxError when the browser is off or the chat is not the
    user's. `require_setting=False` skips only the `browser_enabled` check."""
    if not HARNESS_SANDBOX_ENABLED or (require_setting and not load_browser_enabled()):
        raise OnyxError(OnyxErrorCode.FEATURE_DISABLED, "The browser is turned off.")
    if user.is_anonymous:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Sign in to use the browser.")
    chat_session = get_owned_chat_session(chat_session_id, user.id, db_session)
    if chat_session is None or chat_session.deleted:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat session not found.")
    # Incognito cleanup does not reach the sandbox, so these chats get none.
    if chat_session.incognito_record_mode is not None:
        raise OnyxError(
            OnyxErrorCode.FEATURE_DISABLED, "Incognito chats have no browser."
        )


def _browser_ref(
    chat_session_id: UUID, user: User, *, require_setting: bool = True
) -> HarnessSandboxRef:
    """The user's sandbox, seen from a chat that the user owns (see
    _check_browser_chat). Creates the sandbox row if needed."""
    with get_session_with_current_tenant() as db_session:
        _check_browser_chat(
            chat_session_id, user, db_session, require_setting=require_setting
        )
        sandbox_id = get_or_create_sandbox(db_session, user.id).id
    return HarnessSandboxRef(
        tenant_id=get_current_tenant_id(),
        sandbox_id=sandbox_id,
        session_id=chat_session_id,
    )


def _existing_browser_ref(chat_session_id: UUID, user: User) -> HarnessSandboxRef:
    """Like _browser_ref, for reads: writes nothing, and raises NOT_FOUND
    when the user has no sandbox."""
    with get_session_with_current_tenant() as db_session:
        _check_browser_chat(chat_session_id, user, db_session)
        sandbox_id = get_sandbox_id_by_user_id(db_session, user.id)
    if sandbox_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The chat has no browser files.")
    return HarnessSandboxRef(
        tenant_id=get_current_tenant_id(),
        sandbox_id=sandbox_id,
        session_id=chat_session_id,
    )


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    if websocket.application_state is WebSocketState.CONNECTED:
        try:
            await websocket.close(
                code=code,
                reason=reason.encode()[:_MAX_CLOSE_REASON_BYTES].decode(
                    errors="ignore"
                ),
            )
        except RuntimeError:
            # The client left meanwhile.
            pass


async def _close_refused(websocket: WebSocket, e: OnyxError) -> None:
    code = (
        CLOSE_NOT_FOUND if e.error_code is OnyxErrorCode.NOT_FOUND else CLOSE_FORBIDDEN
    )
    await _close(websocket, code, e.detail)


async def _hold_browser_view(
    sandbox: HarnessSandbox,
    ref: HarnessSandboxRef,
    read_user: Callable[[], Awaitable[User | None]],
) -> OnyxError:
    """Renew the viewer lease while the user may still view the chat (the
    session, the user, the setting, the owner and the chat are checked again
    after each renewal); returns the error that ends the view. A failed
    renewal only lets the lease expire sooner; a check that cannot complete
    raises, which ends the view."""
    while True:
        try:
            await asyncio.to_thread(sandbox.renew_browser_view, ref)
        except Exception:
            logger.warning(
                "chat_browser_view_renew_failed chat=%s", ref.session_id, exc_info=True
            )
        await asyncio.sleep(_VIEW_RENEW_SECONDS)
        try:
            user = await read_user()
            if user is None:
                return OnyxError(
                    OnyxErrorCode.UNAUTHENTICATED, "Your session has ended."
                )
            await asyncio.to_thread(_browser_ref, ref.session_id, user)
        except OnyxError as e:
            return e


async def _viewer_to_service(
    websocket: WebSocket, stream: BrowserStream, chat_session_id: UUID
) -> None:
    """Send the view hello, then forward viewer messages until the viewer
    leaves."""
    await stream.send(view_hello(str(chat_session_id)))
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        if not isinstance(text, str):
            # The viewer sends JSON text only.
            continue
        payload = text.encode()
        if len(payload) <= _MAX_VIEWER_MESSAGE_BYTES:
            await stream.send(BrowserFrame(kind=FrameKind.JSON, payload=payload))


async def _service_to_viewer(websocket: WebSocket, stream: BrowserStream) -> None:
    """Forward service frames until the service closes."""
    while (frame := await stream.receive()) is not None:
        if frame.kind is FrameKind.JPEG:
            await websocket.send_bytes(frame.payload)
        else:
            await websocket.send_text(frame.payload.decode())


async def _pump(
    websocket: WebSocket,
    stream: BrowserStream,
    chat_session_id: UUID,
    lease: "asyncio.Task[OnyxError]",
) -> None:
    """Pump both directions until one ends or the lease ends. The viewer
    leaving ends the view quietly; an ended lease closes the websocket with
    its error's code; anything else, also a check that cannot complete,
    with CLOSE_RECONNECT, and the reconnect checks access again."""
    from_viewer = asyncio.create_task(
        _viewer_to_service(websocket, stream, chat_session_id)
    )
    from_service = asyncio.create_task(_service_to_viewer(websocket, stream))
    pumps = {from_viewer, from_service}
    try:
        done, _ = await asyncio.wait(
            {*pumps, lease}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        # Also on a cancel of this task: no pump outlives it.
        for task in pumps:
            task.cancel()
        await asyncio.gather(*pumps, return_exceptions=True)
    if lease in done and lease.exception() is None:
        await _close_refused(websocket, lease.result())
        return
    viewer_error = from_viewer.exception() if from_viewer in done else None
    viewer_left = from_viewer in done and (
        viewer_error is None or isinstance(viewer_error, WebSocketDisconnect)
    )
    for task in done:
        error = task.exception()
        if error is not None and not isinstance(error, WebSocketDisconnect):
            logger.warning(
                "chat_browser_view_failed chat=%s: %r", chat_session_id, error
            )
    if not viewer_left:
        await _close(websocket, CLOSE_RECONNECT, "The browser connection ended.")


@router.websocket("/sessions/{chat_session_id}/browser/ws")
async def chat_browser_live_view(
    websocket: WebSocket,
    chat_session_id: UUID,
    user: User = Depends(current_user_from_websocket_cookie),
) -> None:
    """The live view of the chat's tabs."""
    # Accepted first, so that a refusal reaches the viewer with its code.
    await websocket.accept()
    try:
        ref = await asyncio.to_thread(_browser_ref, chat_session_id, user)
    except OnyxError as e:
        await _close_refused(websocket, e)
        return
    except Exception:
        logger.warning(
            "chat_browser_view_check_failed chat=%s", chat_session_id, exc_info=True
        )
        await _close(websocket, CLOSE_RECONNECT, "The access check did not complete.")
        return
    sandbox = get_harness_sandbox()
    lease = asyncio.create_task(
        _hold_browser_view(sandbox, ref, lambda: read_websocket_cookie_user(websocket))
    )
    try:
        await websocket.send_json({"type": "starting"})
        try:
            stream = await sandbox.open_browser_stream(ref)
        except Exception as e:
            logger.warning(
                "chat_browser_view_unavailable chat=%s", chat_session_id, exc_info=True
            )
            await _close(
                websocket,
                CLOSE_UNAVAILABLE,
                str(e) if isinstance(e, HarnessSandboxError) else _UNAVAILABLE,
            )
            return
        try:
            await _pump(websocket, stream, chat_session_id, lease)
        finally:
            await stream.aclose()
    except WebSocketDisconnect:
        # The viewer left before the view began.
        return
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


@router.post("/sessions/{chat_session_id}/browser/upload")
def upload_chat_browser_files(
    chat_session_id: UUID,
    files: list[UploadFile],
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> BrowserUploadResponse:
    """Write files for the browser's file chooser into the chat session
    directory; returns their session-relative paths."""
    ref = _browser_ref(chat_session_id, user)
    if not files or len(files) > BROWSER_UPLOAD_MAX_FILES:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Upload 1 to {BROWSER_UPLOAD_MAX_FILES} files at a time.",
        )
    for upload in files:
        if upload.size is None or upload.size > BROWSER_UPLOAD_MAX_BYTES:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                f"Each file must be at most {BROWSER_UPLOAD_MAX_BYTES >> 20} MiB.",
            )
    sandbox = get_harness_sandbox()
    paths: list[str] = []
    with _sandbox_errors_as_onyx_errors():
        for upload in files:
            # A unique folder keeps two uploads apart.
            name = safe_file_name((upload.filename or "",))
            path = f"{BROWSER_UPLOADS_DIR}/{uuid4().hex[:8]}/{name}"
            sandbox.write_file(
                ref, path, upload.file, timeout_seconds=_UPLOAD_TIMEOUT_SECONDS
            )
            paths.append(path)
    return BrowserUploadResponse(paths=paths)


@router.post("/sessions/{chat_session_id}/browser/clear")
def clear_chat_browser_data(
    chat_session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> None:
    """Stop the user's browser and delete its profile and the profile's
    save: sign-ins, cookies and site storage of all the user's chats. Works
    while the `browser_enabled` setting is off, so saved sign-ins can always
    be deleted."""
    ref = _browser_ref(chat_session_id, user, require_setting=False)
    with _sandbox_errors_as_onyx_errors():
        get_harness_sandbox().clear_browser_data(ref)


@router.get("/sessions/{chat_session_id}/browser/downloads/{name}")
def download_chat_browser_file(
    chat_session_id: UUID,
    name: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> StreamingResponse:
    """A file that the browser downloaded for the chat, as an attachment.
    `name` is its name in the chat's downloads directory."""
    ref = _existing_browser_ref(chat_session_id, user)
    if (
        name in ("", ".", "..")
        or any(char in name for char in "/\\\0")
        or len(name.encode()) > _MAX_DOWNLOAD_NAME_BYTES
    ):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Not a valid file name.")
    with _sandbox_errors_as_onyx_errors():
        try:
            chunks = get_harness_sandbox().stream_file(
                ref,
                f"{BROWSER_DOWNLOADS_DIR}/{name}",
                max_bytes=BROWSER_DOWNLOAD_MAX_BYTES,
            )
        except SandboxFileNotFoundError as e:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Download not found.") from e
        except SandboxFileTooLargeError as e:
            raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE, str(e)) from e
    return StreamingResponse(
        chunks,
        media_type="application/octet-stream",
        headers={"Content-Disposition": build_content_disposition("attachment", name)},
    )
