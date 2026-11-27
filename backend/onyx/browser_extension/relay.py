"""The relay between chat turns and the user's Chrome (the Onyx extension).

The extension keeps one websocket open to an API server
(`server/query_and_chat/chrome_browser.py`). A chat turn can run on another
server, so the two meet in the cache:

- Presence: each connected installation renews `presence` while its socket
  lives. `installations` lists the user's installations.
- Commands: a turn pushes onto the `commands` list of the installation's
  current connection; the server that holds that socket pops and sends them.
  A replaced socket reads only its own list, so it never takes a message
  meant for the newer one. A command carries its deadline, so a late one is
  dropped, never run, and the list expires when nothing reads it.
- Results: the socket's server pushes the answer onto `result:{command_id}`;
  the turn waits on it with a bounded poll and checks its cancel signal.
- Grants: the user shares tabs and sites with one chat in the extension. The
  extension and the server both keep the grant, and both check it. One
  installation serves one chat at a time; a new grant ends the old one.
  Grant changes of a chat run under the chat's lock, so a late tab report
  cannot bring back a grant that Stop ended.

Everything here lives in the cache with a TTL. Chat history is the record.
"""

import json
import time
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue, ValidationError

from onyx.browser_extension.models import (
    ChromeGrant,
    CommandResult,
    GrantReport,
    GrantRequest,
    Presence,
)
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.llm.cancellation import current_cancellation
from onyx.tools.tool_implementations.sandbox.browser_tools import BrowserBackend
from onyx.tools.tool_implementations.sandbox.errors import tool_error
from onyx.tools.tool_implementations.sandbox.models import BrowserTarget
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PREFIX = "chrome_browser"
# The extension pings every 20 s; two lost pings end its presence.
PRESENCE_SECONDS = 45
_INSTALLATIONS_SECONDS = 24 * 3600
REQUEST_SECONDS = 300
_RESULT_SECONDS = 120
# Longest grant that the extension offers.
MAX_GRANT_SECONDS = 8 * 3600
# One poll of the result list; the turn checks its cancel signal between polls.
_POLL_SECONDS = 1
_GRANT_LOCK_SECONDS = 10
MAX_INSTALLATIONS = 20


def _presence_key(user_id: UUID, installation_id: UUID) -> str:
    return f"{_PREFIX}:presence:{user_id}:{installation_id}"


def _installations_key(user_id: UUID) -> str:
    return f"{_PREFIX}:installations:{user_id}"


def commands_key(user_id: UUID, installation_id: UUID, connection_id: str) -> str:
    return f"{_PREFIX}:commands:{user_id}:{installation_id}:{connection_id}"


def _result_key(command_id: str) -> str:
    return f"{_PREFIX}:result:{command_id}"


def _request_key(chat_session_id: UUID) -> str:
    return f"{_PREFIX}:request:{chat_session_id}"


def _cancelled_key(command_id: str) -> str:
    return f"{_PREFIX}:cancelled:{command_id}"


def _grant_key(chat_session_id: UUID) -> str:
    return f"{_PREFIX}:grant:{chat_session_id}"


def _grant_lock_key(chat_session_id: UUID) -> str:
    return f"{_PREFIX}:grant_lock:{chat_session_id}"


def _installation_grant_key(user_id: UUID, installation_id: UUID) -> str:
    return f"{_PREFIX}:installation_grant:{user_id}:{installation_id}"


def _cache(tenant_id: str) -> CacheBackend:
    return get_cache_backend(tenant_id=tenant_id)


def _load[ModelT: BaseModel](
    cache: CacheBackend, key: str, model: type[ModelT]
) -> ModelT | None:
    raw = cache.get(key)
    if raw is None:
        return None
    try:
        return model.model_validate_json(raw)
    except ValidationError:
        logger.warning("Dropping a bad cache value at %s", key)
        cache.delete(key)
        return None


# ---- presence ----


def _add_installation(
    cache: CacheBackend, user_id: UUID, installation_id: UUID
) -> None:
    installations = _installations_key(user_id)
    cache.set_add(installations, str(installation_id))
    cache.expire(installations, _INSTALLATIONS_SECONDS)


def renew_presence(tenant_id: str, user_id: UUID, presence: Presence) -> bool:
    """Renew the installation's presence for this connection. False when a
    newer connection of the installation took it over."""
    cache = _cache(tenant_id)
    if not owns_presence(tenant_id, user_id, presence):
        return False
    cache.set(
        _presence_key(user_id, presence.installation_id),
        presence.model_dump_json(),
        ex=PRESENCE_SECONDS,
    )
    _add_installation(cache, user_id, presence.installation_id)
    return True


def claim_presence(tenant_id: str, user_id: UUID, presence: Presence) -> None:
    """Make this connection the installation's one connection."""
    cache = _cache(tenant_id)
    cache.set(
        _presence_key(user_id, presence.installation_id),
        presence.model_dump_json(),
        ex=PRESENCE_SECONDS,
    )
    _add_installation(cache, user_id, presence.installation_id)


def owns_presence(tenant_id: str, user_id: UUID, presence: Presence) -> bool:
    """False when a newer connection of the installation took it over. A
    lapsed presence still belongs to its connection until another claims it."""
    current = _load(
        _cache(tenant_id), _presence_key(user_id, presence.installation_id), Presence
    )
    return current is None or current.connection_id == presence.connection_id


def drop_presence(tenant_id: str, user_id: UUID, presence: Presence) -> None:
    cache = _cache(tenant_id)
    cache.delete_if_value(
        _presence_key(user_id, presence.installation_id),
        presence.model_dump_json().encode(),
    )


def connected_installations(tenant_id: str, user_id: UUID) -> list[Presence]:
    cache = _cache(tenant_id)
    members = cache.set_members(_installations_key(user_id), limit=MAX_INSTALLATIONS)
    present: list[Presence] = []
    for member in members:
        try:
            installation_id = UUID(member.decode())
        except ValueError:
            continue
        presence = _load(cache, _presence_key(user_id, installation_id), Presence)
        if presence is not None:
            present.append(presence)
        else:
            cache.set_remove(_installations_key(user_id), member)
    return present


def _connection(
    cache: CacheBackend, user_id: UUID, installation_id: UUID
) -> Presence | None:
    return _load(cache, _presence_key(user_id, installation_id), Presence)


# ---- messages to the extension ----


def _send(
    cache: CacheBackend,
    user_id: UUID,
    presence: Presence,
    message: dict[str, JsonValue],
    deadline: float,
) -> None:
    key = commands_key(user_id, presence.installation_id, presence.connection_id)
    cache.rpush(key, json.dumps({**message, "deadline": deadline}))
    # No message lives past REQUEST_SECONDS, so an unread list goes with them.
    cache.expire(key, REQUEST_SECONDS)


def pop_message(
    tenant_id: str, user_id: UUID, presence: Presence
) -> dict[str, JsonValue] | None:
    """The next live message for this connection, waiting up to one poll.
    Messages past their deadline are dropped."""
    cache = _cache(tenant_id)
    popped = cache.blpop(
        [commands_key(user_id, presence.installation_id, presence.connection_id)],
        timeout=_POLL_SECONDS,
    )
    if popped is None:
        return None
    try:
        message = json.loads(popped[1])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict):
        return None
    deadline = message.get("deadline")
    if not isinstance(deadline, (int, float)) or deadline < time.time():
        return None
    command_id = message.get("command_id")
    if isinstance(command_id, str) and cache.exists(_cancelled_key(command_id)):
        return None
    return message


def push_result(tenant_id: str, command_id: str, result: CommandResult) -> None:
    cache = _cache(tenant_id)
    key = _result_key(command_id)
    cache.rpush(key, result.model_dump_json())
    cache.expire(key, _RESULT_SECONDS)


# ---- grants ----


def load_grant(
    tenant_id: str, chat_session_id: UUID, user_id: UUID
) -> ChromeGrant | None:
    grant = _load(_cache(tenant_id), _grant_key(chat_session_id), ChromeGrant)
    if grant is None or grant.user_id != user_id or grant.expires_at <= time.time():
        return None
    return grant


def request_grant(
    tenant_id: str,
    user_id: UUID,
    chat_session_id: UUID,
    presence: Presence,
    *,
    chat_title: str,
    account: str,
) -> GrantRequest:
    """Ask the installation's connection to show its consent window for the
    chat."""
    cache = _cache(tenant_id)
    request = GrantRequest(
        request_id=uuid4().hex,
        user_id=user_id,
        installation_id=presence.installation_id,
        state="pending",
    )
    cache.set(
        _request_key(chat_session_id), request.model_dump_json(), ex=REQUEST_SECONDS
    )
    _send(
        cache,
        user_id,
        presence,
        {
            "type": "grant_request",
            "request_id": request.request_id,
            "chat_session_id": str(chat_session_id),
            "chat_title": chat_title,
            "account": account,
        },
        time.time() + REQUEST_SECONDS,
    )
    return request


def load_chat_request(
    tenant_id: str, chat_session_id: UUID, user_id: UUID
) -> GrantRequest | None:
    request = _load(_cache(tenant_id), _request_key(chat_session_id), GrantRequest)
    if request is None or request.user_id != user_id:
        return None
    return request


def _pending_request(
    cache: CacheBackend,
    user_id: UUID,
    installation_id: UUID,
    chat_session_id: UUID,
    request_id: str,
) -> GrantRequest | None:
    """The chat's request when it is this installation's pending one."""
    request = _load(cache, _request_key(chat_session_id), GrantRequest)
    if (
        request is None
        or request.request_id != request_id
        or request.state != "pending"
        or request.user_id != user_id
        or request.installation_id != installation_id
    ):
        return None
    return request


def deny_request(
    tenant_id: str,
    user_id: UUID,
    installation_id: UUID,
    chat_session_id: UUID,
    request_id: str,
) -> None:
    cache = _cache(tenant_id)
    request = _pending_request(
        cache, user_id, installation_id, chat_session_id, request_id
    )
    if request is None:
        return
    request.state = "denied"
    cache.set(
        _request_key(chat_session_id), request.model_dump_json(), ex=REQUEST_SECONDS
    )


def save_grant(
    tenant_id: str, user_id: UUID, installation_id: UUID, report: GrantReport
) -> ChromeGrant | None:
    """Store an approved or changed grant. An approval must answer this
    installation's pending request for the chat; a change must be of this
    installation's grant. Returns None when neither holds."""
    cache = _cache(tenant_id)
    chat_session_id = report.chat_session_id
    with cache.lock(_grant_lock_key(chat_session_id), timeout=_GRANT_LOCK_SECONDS):
        existing = _load(cache, _grant_key(chat_session_id), ChromeGrant)
        if report.request_id is not None:
            if (
                _pending_request(
                    cache, user_id, installation_id, chat_session_id, report.request_id
                )
                is None
            ):
                return None
            cache.delete(_request_key(chat_session_id))
        elif (
            existing is None
            or existing.user_id != user_id
            or existing.installation_id != installation_id
        ):
            return None
        now = time.time()
        expires_at = min(report.expires_at, now + MAX_GRANT_SECONDS)
        if expires_at <= now or not report.tabs:
            _end_grant(cache, user_id, chat_session_id, notify=False)
            return None
        # One installation serves one chat: a new grant ends the one before.
        installation_key = _installation_grant_key(user_id, installation_id)
        previous = cache.get(installation_key)
        if previous is not None and previous.decode() != str(chat_session_id):
            previous_chat = UUID(previous.decode())
            previous_grant = _load(cache, _grant_key(previous_chat), ChromeGrant)
            # Only while that grant is still this installation's.
            if (
                previous_grant is not None
                and previous_grant.installation_id == installation_id
            ):
                cache.delete(_grant_key(previous_chat))
        # A chat moved from another installation leaves that one free.
        if existing is not None and existing.installation_id != installation_id:
            cache.delete_if_value(
                _installation_grant_key(user_id, existing.installation_id),
                str(chat_session_id).encode(),
            )
        grant = ChromeGrant(
            user_id=user_id,
            installation_id=installation_id,
            chat_session_id=chat_session_id,
            tabs=report.tabs,
            origins=report.origins,
            expires_at=expires_at,
        )
        ttl = max(1, int(expires_at - now))
        cache.set(_grant_key(chat_session_id), grant.model_dump_json(), ex=ttl)
        cache.set(installation_key, str(chat_session_id), ex=ttl)
        return grant


def end_grant(
    tenant_id: str, user_id: UUID, chat_session_id: UUID, *, notify: bool
) -> None:
    """End the chat's grant. `notify` also tells the extension, for a stop
    from Onyx; a stop in the extension already ended it there. An extension
    that is not connected learns it when it reports its grant on reconnect."""
    cache = _cache(tenant_id)
    with cache.lock(_grant_lock_key(chat_session_id), timeout=_GRANT_LOCK_SECONDS):
        _end_grant(cache, user_id, chat_session_id, notify=notify)


def _end_grant(
    cache: CacheBackend, user_id: UUID, chat_session_id: UUID, *, notify: bool
) -> None:
    grant = _load(cache, _grant_key(chat_session_id), ChromeGrant)
    if grant is None or grant.user_id != user_id:
        return
    cache.delete(_grant_key(chat_session_id))
    cache.delete_if_value(
        _installation_grant_key(user_id, grant.installation_id),
        str(chat_session_id).encode(),
    )
    presence = _connection(cache, user_id, grant.installation_id)
    if notify and presence is not None:
        _send(
            cache,
            user_id,
            presence,
            {"type": "end_grant", "chat_session_id": str(chat_session_id)},
            time.time() + REQUEST_SECONDS,
        )


# ---- the tools' backend ----

NO_GRANT_MESSAGE = (
    "The user's Chrome is no longer shared with this chat. Ask the user to "
    "share a tab again from the chat's browser panel."
)
NOT_CONNECTED_MESSAGE = (
    "The user's Chrome is not connected to Onyx. Ask the user to open Chrome "
    "with the Onyx extension signed in."
)
LOST_MESSAGE = (
    "The user's Chrome did not answer, so the outcome is unknown. Check the "
    "page with browser_status or browser_snapshot before you retry."
)


class ChromeBrowser(BrowserBackend):
    """The user's Chrome, through the Onyx extension. Each call checks the
    chat's grant and the installation's presence first."""

    target = BrowserTarget.CHROME

    def __init__(self, *, tenant_id: str, user_id: UUID, chat_session_id: UUID) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._chat_session_id = chat_session_id

    def call(
        self, method: str, params: dict[str, JsonValue], *, timeout_seconds: float
    ) -> dict[str, JsonValue]:
        if "screenshotPath" in params:
            raise tool_error("screenshot_path is not available in the user's Chrome.")
        if params.get("action") == "upload":
            raise tool_error("upload is not available in the user's Chrome.")
        grant = load_grant(self._tenant_id, self._chat_session_id, self._user_id)
        if grant is None:
            raise tool_error(NO_GRANT_MESSAGE)
        cache = _cache(self._tenant_id)
        presence = _connection(cache, self._user_id, grant.installation_id)
        if presence is None:
            raise tool_error(NOT_CONNECTED_MESSAGE)
        command_id = uuid4().hex
        deadline = time.time() + timeout_seconds
        _send(
            cache,
            self._user_id,
            presence,
            {
                "type": "command",
                "command_id": command_id,
                "chat_session_id": str(self._chat_session_id),
                "method": method,
                "params": params,
            },
            deadline,
        )
        cancellation = current_cancellation()
        while time.time() < deadline:
            if cancellation is not None and cancellation.cancelled:
                # A command still in the list must not run after the turn stopped.
                cache.set(
                    _cancelled_key(command_id),
                    "1",
                    ex=max(1, int(deadline - time.time()) + 1),
                )
                cancellation.check()
            popped = cache.blpop([_result_key(command_id)], timeout=_POLL_SECONDS)
            if popped is not None:
                return _answer(popped[1])
            # The command waits in the list of the connection that it went
            # to; a lost or replaced connection never answers it.
            current = _connection(cache, self._user_id, grant.installation_id)
            if current is None or current.connection_id != presence.connection_id:
                raise tool_error(LOST_MESSAGE)
        raise tool_error(LOST_MESSAGE)


def _answer(raw: bytes) -> dict[str, JsonValue]:
    reply = CommandResult.model_validate_json(raw)
    if reply.ok:
        return reply.result or {}
    raise tool_error(
        reply.error.message if reply.error else "The user's Chrome call failed."
    )
