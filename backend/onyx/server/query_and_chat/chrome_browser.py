"""The routes of the user's own Chrome as a chat browser (the Onyx
extension). The relay logic is in `onyx/browser_extension/relay.py`.

- POST /chat/browser/extension/token: a single-use token for the socket.
- WS /chat/browser/extension/ws: the extension's one socket. It sends a
  hello, then pings, command results and grant reports; it gets commands,
  grant requests and grant ends.
- GET/POST/DELETE /chat/sessions/{id}/browser/chrome: the chat's state, a
  request to share tabs (the extension asks the user), and a stop.
"""

import asyncio
import json
from typing import Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from onyx.auth.permissions import require_permission
from onyx.auth.users import current_user_from_extension_token
from onyx.browser_extension import relay
from onyx.browser_extension.models import Presence
from onyx.browser_extension.tokens import issue_extension_token
from onyx.db.chat import get_owned_chat_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.models import (
    ChromeBrowserState,
    CommandResultMessage,
    ExtensionHello,
    ExtensionTokenResponse,
    GrantDenied,
    GrantEnded,
    GrantReportMessage,
)
from onyx.server.settings.store import load_browser_enabled
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/chat")

CLOSE_FORBIDDEN: Final = 4403
# A newer socket of the same installation took over.
CLOSE_REPLACED: Final = 4409
_HELLO_SECONDS = 10.0
_MAX_MESSAGE_BYTES = 4 << 20
_DISABLED = "Chats cannot use your Chrome in this workspace."


def _check_enabled(user: User) -> None:
    if user.is_anonymous:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Sign in to use your Chrome.")
    if not load_browser_enabled(chrome=True):
        raise OnyxError(OnyxErrorCode.FEATURE_DISABLED, _DISABLED)


def _owned_chat_title(chat_session_id: UUID, user: User) -> str:
    with get_session_with_current_tenant() as db_session:
        chat = get_owned_chat_session(chat_session_id, user.id, db_session)
        if chat is None or chat.deleted or chat.incognito_record_mode is not None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat not found.")
        return chat.description or "Untitled chat"


@router.post("/browser/extension/token")
def create_extension_token(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ExtensionTokenResponse:
    _check_enabled(user)
    return ExtensionTokenResponse(
        token=issue_extension_token(user.id, get_current_tenant_id())
    )


@router.get("/sessions/{chat_session_id}/browser/chrome")
def get_chrome_browser_state(
    chat_session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ChromeBrowserState:
    _check_enabled(user)
    _owned_chat_title(chat_session_id, user)
    tenant_id = get_current_tenant_id()
    grant = relay.load_grant(tenant_id, chat_session_id, user.id)
    request = relay.load_chat_request(tenant_id, chat_session_id, user.id)
    return ChromeBrowserState(
        installations=list(relay.connected_installations(tenant_id, user.id)),
        request=None if grant is not None or request is None else request.state,
        grant=grant,
    )


@router.post("/sessions/{chat_session_id}/browser/chrome")
def request_chrome_browser(
    chat_session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ChromeBrowserState:
    """Ask the user's Chrome to show its consent window for this chat."""
    _check_enabled(user)
    title = _owned_chat_title(chat_session_id, user)
    tenant_id = get_current_tenant_id()
    chosen = next(iter(relay.connected_installations(tenant_id, user.id)), None)
    if chosen is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Chrome with the Onyx extension is not connected.",
        )
    relay.request_grant(
        tenant_id,
        user.id,
        chat_session_id,
        chosen,
        chat_title=title,
        account=user.email,
    )
    return get_chrome_browser_state(chat_session_id, user)


@router.delete("/sessions/{chat_session_id}/browser/chrome")
def stop_chrome_browser(
    chat_session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> None:
    """End the chat's grant. Works while the feature is off, so a user can
    always stop."""
    _owned_chat_title(chat_session_id, user)
    relay.end_grant(get_current_tenant_id(), user.id, chat_session_id, notify=True)


@router.websocket("/browser/extension/ws")
async def chrome_extension_socket(
    websocket: WebSocket,
    user: User = Depends(current_user_from_extension_token),
) -> None:
    tenant_id = get_current_tenant_id()
    await websocket.accept()
    refusal = await asyncio.to_thread(_refusal, user.id)
    if refusal is not None:
        await websocket.close(code=refusal[0], reason=refusal[1])
        return
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), _HELLO_SECONDS)
        hello = ExtensionHello.model_validate_json(raw)
    except (TimeoutError, ValidationError, WebSocketDisconnect):
        await _close(websocket, 1008, "Send a hello first.")
        return
    presence = Presence(
        installation_id=hello.installation_id,
        connection_id=uuid4().hex,
        label=hello.label,
        version=hello.version,
    )
    await asyncio.to_thread(relay.claim_presence, tenant_id, user.id, presence)
    await websocket.send_json({"type": "welcome", "account": user.email})
    reader = asyncio.create_task(_read(websocket, tenant_id, user, presence))
    pump = asyncio.create_task(_pump(websocket, tenant_id, user, presence))
    try:
        await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
        close = reader.result() if reader.done() else pump.result()
        if close is not None:
            await _close(websocket, *close)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("The Chrome extension socket failed")
        await _close(websocket, 1011, "Server error.")
    finally:
        for task in (reader, pump):
            task.cancel()
        await asyncio.gather(reader, pump, return_exceptions=True)
        await asyncio.to_thread(relay.drop_presence, tenant_id, user.id, presence)


def _refusal(user_id: UUID) -> tuple[int, str] | None:
    """The close for a socket that may no longer serve: the admin switch is
    off, or the account is no longer active."""
    if not load_browser_enabled(chrome=True):
        return CLOSE_FORBIDDEN, _DISABLED
    with get_session_with_current_tenant() as db_session:
        current = fetch_user_by_id(db_session, user_id)
        if current is None or not current.is_active:
            return CLOSE_FORBIDDEN, "This account is not active."
    return None


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    if websocket.application_state is WebSocketState.CONNECTED:
        try:
            await websocket.close(code=code, reason=reason)
        except RuntimeError:
            pass


async def _read(
    websocket: WebSocket, tenant_id: str, user: User, presence: Presence
) -> tuple[int, str] | None:
    """Handle the extension's messages. Returns the close to send, or None
    when the extension left."""
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return None
        if len(raw.encode()) > _MAX_MESSAGE_BYTES:
            return 1009, "Message too large."
        try:
            message = json.loads(raw)
            kind = message.get("type") if isinstance(message, dict) else None
            match kind:
                case "ping":
                    refusal = await asyncio.to_thread(_refusal, user.id)
                    if refusal is not None:
                        return refusal
                    renewed = await asyncio.to_thread(
                        relay.renew_presence, tenant_id, user.id, presence
                    )
                    if not renewed:
                        return CLOSE_REPLACED, "Another connection took over."
                    await websocket.send_json({"type": "pong"})
                case "result":
                    result = CommandResultMessage.model_validate(message)
                    await asyncio.to_thread(
                        relay.push_result,
                        tenant_id,
                        result.command_id,
                        result,
                    )
                case "grant":
                    report = GrantReportMessage.model_validate(message).grant
                    refusal = await asyncio.to_thread(_refusal, user.id)
                    if refusal is not None:
                        return refusal
                    grant = await asyncio.to_thread(
                        relay.save_grant,
                        tenant_id,
                        user.id,
                        presence.installation_id,
                        report,
                    )
                    await websocket.send_json(
                        {
                            "type": "grant_saved" if grant else "end_grant",
                            "chat_session_id": str(report.chat_session_id),
                        }
                    )
                case "grant_denied":
                    denied = GrantDenied.model_validate(message)
                    await asyncio.to_thread(
                        relay.deny_request,
                        tenant_id,
                        user.id,
                        presence.installation_id,
                        denied.chat_session_id,
                        denied.request_id,
                    )
                case "grant_ended":
                    ended = GrantEnded.model_validate(message)
                    await asyncio.to_thread(
                        relay.end_grant,
                        tenant_id,
                        user.id,
                        ended.chat_session_id,
                        notify=False,
                        installation_id=presence.installation_id,
                    )
                case _:
                    logger.warning("Unknown Chrome extension message %r", kind)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Bad Chrome extension message: %s", e)


async def _pump(
    websocket: WebSocket, tenant_id: str, user: User, presence: Presence
) -> tuple[int, str]:
    """Send this connection's queued messages as they arrive. Returns the
    close to send when the connection may no longer serve."""
    while True:
        if not await asyncio.to_thread(
            relay.owns_presence, tenant_id, user.id, presence
        ):
            return CLOSE_REPLACED, "Another connection took over."
        message = await asyncio.to_thread(
            relay.pop_message, tenant_id, user.id, presence
        )
        if message is None:
            continue
        refusal = await asyncio.to_thread(_refusal, user.id)
        if refusal is not None:
            return refusal
        await websocket.send_json(message)
