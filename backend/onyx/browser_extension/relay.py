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
- Grants: a turn binds a chat to one installation (`bind_chat`) and the
  extension answers with its tabs. The user approves sites in the Onyx chat,
  never in the extension; each command carries the sites that the chat may
  use now, and the extension enforces them. One installation serves one chat
  at a time; a new binding ends the old one. Grant changes of a chat run
  under the chat's lock, so a late tab report cannot bring back a grant that
  Stop ended.

Everything here lives in the cache with a TTL. Chat history is the record.
"""

import json
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue, ValidationError

from onyx.browser_extension.models import (
    ChromeGrant,
    CommandResult,
    GrantReport,
    GrantTab,
    Presence,
)
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.integration_policy import get_session_granted_actions
from onyx.llm.cancellation import current_cancellation
from onyx.tools.models import ToolApprovalDetails
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


def _cancelled_key(command_id: str) -> str:
    return f"{_PREFIX}:cancelled:{command_id}"


def _grant_key(chat_session_id: UUID) -> str:
    return f"{_PREFIX}:grant:{chat_session_id}"


def _grant_lock_key(chat_session_id: UUID) -> str:
    return f"{_PREFIX}:grant_lock:{chat_session_id}"


def _installation_lock_key(user_id: UUID, installation_id: UUID) -> str:
    return f"{_PREFIX}:installation_lock:{user_id}:{installation_id}"


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
    key = _presence_key(user_id, presence.installation_id)
    value = presence.model_dump_json()
    # Compare and set, so a newer connection's claim between the check and
    # the write is never overwritten.
    current = cache.get(key)
    if current is None:
        renewed = cache.set_if_absent(key, value, ex=PRESENCE_SECONDS)
    else:
        owner = _load(cache, key, Presence)
        renewed = (
            owner is not None
            and owner.connection_id == presence.connection_id
            and cache.replace_if_value(key, current, value, ex=PRESENCE_SECONDS)
        )
    if renewed:
        _add_installation(cache, user_id, presence.installation_id)
    return renewed


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


def bind_chat(
    tenant_id: str,
    user_id: UUID,
    chat_session_id: UUID,
    presence: Presence,
    *,
    chat_title: str,
    window_id: int | None,
    tab_id: int | None,
    side_panel: bool,
) -> ChromeGrant:
    """Bind the chat to the installation and tell its extension. A chat with
    a grant on another installation loses it; the installation's grant of
    another chat ends without a message, since the extension replaces it on
    the bind. A new bind of the same installation keeps its tabs and sites."""
    cache = _cache(tenant_id)
    installation_id = presence.installation_id
    now = time.time()
    expires_at = now + MAX_GRANT_SECONDS
    with cache.lock(_grant_lock_key(chat_session_id), timeout=_GRANT_LOCK_SECONDS):
        existing = _load(cache, _grant_key(chat_session_id), ChromeGrant)
        if existing is not None and existing.user_id != user_id:
            existing = None
        if existing is not None and existing.installation_id != installation_id:
            _end_grant(cache, user_id, chat_session_id, notify=True)
            existing = None
        # The installation's own lock (always taken after a chat's) keeps two
        # chats' binds from both keeping the installation.
        with cache.lock(
            _installation_lock_key(user_id, installation_id),
            timeout=_GRANT_LOCK_SECONDS,
        ):
            _drop_other_chat(cache, user_id, installation_id, chat_session_id)
            tabs = existing.tabs if existing is not None else []
            current = existing.current if existing is not None else None
            if tab_id is not None:
                current = str(tab_id)
                if not any(tab.id == current for tab in tabs):
                    tabs = [*tabs, GrantTab(id=current)]
            grant = ChromeGrant(
                user_id=user_id,
                installation_id=installation_id,
                chat_session_id=chat_session_id,
                chat_title=chat_title[:500],
                tabs=tabs,
                current=current,
                expires_at=expires_at,
                side_panel=side_panel,
                window_id=window_id,
                once_origins=existing.once_origins if existing is not None else [],
                once_response_id=(
                    existing.once_response_id if existing is not None else None
                ),
            )
            ttl = max(1, int(expires_at - now))
            cache.set(_grant_key(chat_session_id), grant.model_dump_json(), ex=ttl)
            cache.set(
                _installation_grant_key(user_id, installation_id),
                str(chat_session_id),
                ex=ttl,
            )
    _send(
        cache,
        user_id,
        presence,
        {
            "type": "bind",
            "chat_session_id": str(chat_session_id),
            "chat_title": grant.chat_title,
            "window_id": window_id,
            "tab_id": tab_id,
            "side_panel": side_panel,
            "expires_at": expires_at,
        },
        now + REQUEST_SECONDS,
    )
    return grant


def _drop_other_chat(
    cache: CacheBackend, user_id: UUID, installation_id: UUID, chat_session_id: UUID
) -> None:
    """Delete the keys of this installation's grant of another chat."""
    previous = cache.get(_installation_grant_key(user_id, installation_id))
    if previous is None or previous.decode() == str(chat_session_id):
        return
    previous_key = _grant_key(UUID(previous.decode()))
    previous_raw = cache.get(previous_key)
    previous_grant = _load(cache, previous_key, ChromeGrant)
    # Only while that grant is still this installation's: compare and
    # delete, since another installation may take that chat meanwhile.
    if (
        previous_raw is not None
        and previous_grant is not None
        and previous_grant.installation_id == installation_id
    ):
        cache.delete_if_value(previous_key, previous_raw)


def _store_grant(cache: CacheBackend, grant: ChromeGrant, now: float) -> None:
    ttl = max(1, int(grant.expires_at - now))
    cache.set(_grant_key(grant.chat_session_id), grant.model_dump_json(), ex=ttl)


def save_grant(
    tenant_id: str, user_id: UUID, installation_id: UUID, report: GrantReport
) -> ChromeGrant | None:
    """Store the tabs that the extension reports for a grant that this
    installation holds. Returns None when it holds none (the extension then
    ends its own)."""
    cache = _cache(tenant_id)
    chat_session_id = report.chat_session_id
    with cache.lock(_grant_lock_key(chat_session_id), timeout=_GRANT_LOCK_SECONDS):
        grant = _load(cache, _grant_key(chat_session_id), ChromeGrant)
        now = time.time()
        if (
            grant is None
            or grant.user_id != user_id
            or grant.installation_id != installation_id
        ):
            return None
        if grant.expires_at <= now:
            _end_grant(cache, user_id, chat_session_id, notify=False)
            return None
        grant.tabs = report.tabs
        grant.current = report.current
        _store_grant(cache, grant, now)
        return grant


def end_grant(
    tenant_id: str,
    user_id: UUID,
    chat_session_id: UUID,
    *,
    notify: bool,
    installation_id: UUID | None = None,
) -> None:
    """End the chat's grant. `notify` also tells
    the extension, for a stop from Onyx; a stop in the extension already
    ended it there, and passes its `installation_id`, so it ends only a grant
    that it holds. An extension that is not connected learns of the end when
    it reports its grant on reconnect."""
    cache = _cache(tenant_id)
    with cache.lock(_grant_lock_key(chat_session_id), timeout=_GRANT_LOCK_SECONDS):
        _end_grant(
            cache,
            user_id,
            chat_session_id,
            notify=notify,
            installation_id=installation_id,
        )


def _end_grant(
    cache: CacheBackend,
    user_id: UUID,
    chat_session_id: UUID,
    *,
    notify: bool,
    installation_id: UUID | None = None,
) -> None:
    grant = _load(cache, _grant_key(chat_session_id), ChromeGrant)
    if grant is None or grant.user_id != user_id:
        return
    if installation_id is not None and grant.installation_id != installation_id:
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
    "The user's Chrome is no longer connected to this chat: the user stopped "
    "it or closed the side panel."
)
SITE_ACTION_PREFIX = "onyx:chrome.site:"
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

    def __init__(
        self,
        *,
        tenant_id: str,
        user_id: UUID,
        chat_session_id: UUID,
        response_id: int,
    ) -> None:
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._chat_session_id = chat_session_id
        self._response_id = response_id

    def _allowed_origins(self, grant: ChromeGrant) -> set[str]:
        """The sites that the chat may use now: the ones that "Approve for
        this chat" allowed, and the ones that "Approve once" allowed in this
        response."""
        allowed = session_origins(self._tenant_id, self._chat_session_id)
        if grant.once_response_id == self._response_id:
            allowed.update(grant.once_origins)
        return allowed

    def site_approval(
        self, method: str, params: dict[str, JsonValue]
    ) -> ToolApprovalDetails | None:
        grant = load_grant(self._tenant_id, self._chat_session_id, self._user_id)
        if grant is None:
            return None
        origin = _target_origin(method, params, grant)
        if origin is None or origin in self._allowed_origins(grant):
            return None
        return ToolApprovalDetails(
            display_name=f"Use {urlsplit(origin).netloc} in your Chrome",
            payload={"site": origin},
            action_id=f"{SITE_ACTION_PREFIX}{origin}",
        )

    def _record_once(self, origin: str) -> None:
        """Keep a site that this response's call used without a chat approval."""
        cache = _cache(self._tenant_id)
        with cache.lock(
            _grant_lock_key(self._chat_session_id), timeout=_GRANT_LOCK_SECONDS
        ):
            grant = _load(cache, _grant_key(self._chat_session_id), ChromeGrant)
            if grant is None:
                return
            if grant.once_response_id != self._response_id:
                grant.once_origins = []
                grant.once_response_id = self._response_id
            if origin not in grant.once_origins:
                grant.once_origins.append(origin)
            _store_grant(cache, grant, time.time())

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
        origin = _target_origin(method, params, grant)
        allowed = self._allowed_origins(grant)
        if origin is not None and origin not in allowed:
            # The call got here, so the user approved it once, or approvals
            # are off.
            self._record_once(origin)
            allowed.add(origin)
        command_id = uuid4().hex
        deadline = time.time() + timeout_seconds
        cancellation = current_cancellation()
        # A turn stopped during the lookups above sends nothing.
        if cancellation is not None:
            cancellation.check()
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
                "origins": sorted(allowed),
            },
            deadline,
        )
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


def session_origins(tenant_id: str, chat_session_id: UUID) -> set[str]:
    """The sites that "Approve for this chat" allowed in the chat."""
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        actions = get_session_granted_actions(db_session, chat_session_id, None)
    return {
        action.removeprefix(SITE_ACTION_PREFIX)
        for action in actions
        if action.startswith(SITE_ACTION_PREFIX)
    }


def normalize_origin(url: str) -> str | None:
    """`scheme://host[:port]` of a URL, lowercase; a bare host is https. None
    for other schemes and for text that is no URL."""
    text = url.strip()
    if "://" not in text:
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname}" + (f":{port}" if port else "")


def _target_origin(
    method: str, params: dict[str, JsonValue], grant: ChromeGrant
) -> str | None:
    """The site that a call acts on, or None when it is not known."""
    url = params.get("url")
    if method in ("open", "navigate") and isinstance(url, str):
        return normalize_origin(url)
    tab = params.get("tab")
    tab_id = tab if isinstance(tab, str) else grant.current
    for known in grant.tabs:
        if known.id == tab_id:
            return known.origin or None
    return None


def _answer(raw: bytes) -> dict[str, JsonValue]:
    reply = CommandResult.model_validate_json(raw)
    if reply.ok:
        return reply.result or {}
    raise tool_error(
        reply.error.message if reply.error else "The user's Chrome call failed."
    )
