"""The relay between a chat turn and the user's Chrome
(onyx/browser_extension/relay.py), on both cache backends, with the
extension's side played by a thread."""

import json
import threading
import time
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from onyx.browser_extension import relay
from onyx.browser_extension.relay import (
    ChromeBrowser,
    CommandError,
    CommandResult,
    GrantReport,
    GrantTab,
    Presence,
)
from onyx.cache.interface import CacheBackend
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.tools.models import ToolCallException

_TENANT = "public"


@pytest.fixture(autouse=True)
def _use_cache(cache: CacheBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relay, "_cache", lambda _tenant_id: cache)


def _shared_chat() -> tuple[UUID, UUID, Presence]:
    """A user whose connected Chrome shares a tab with a new chat."""
    user_id, chat_id = uuid4(), uuid4()
    presence = Presence(
        installation_id=uuid4(), connection_id="c1", label="Chrome", version="1.3"
    )
    relay.claim_presence(_TENANT, user_id, presence)
    request = relay.request_grant(
        _TENANT,
        user_id,
        chat_id,
        presence.installation_id,
        chat_title="Chat",
        account="a@example.com",
    )
    message = relay.pop_message(_TENANT, user_id, presence.installation_id)
    assert message is not None and message["type"] == "grant_request"
    grant = relay.save_grant(
        _TENANT,
        user_id,
        presence.installation_id,
        GrantReport(
            chat_session_id=chat_id,
            request_id=request.request_id,
            tabs=[GrantTab(id="1", title="Wiki", url="https://wiki.example/")],
            origins=["https://wiki.example"],
            expires_at=time.time() + 600,
        ),
    )
    assert grant is not None
    return user_id, chat_id, presence


def _extension(
    user_id: UUID,
    presence: Presence,
    answer: Callable[[dict[str, JsonValue]], CommandResult],
) -> threading.Thread:
    """Answers the first command the way the extension does."""

    def run() -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            message = relay.pop_message(_TENANT, user_id, presence.installation_id)
            if message is not None and message["type"] == "command":
                relay.push_result(_TENANT, str(message["command_id"]), answer(message))
                return

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_a_command_round_trips_through_the_cache() -> None:
    user_id, chat_id, presence = _shared_chat()
    thread = _extension(
        user_id,
        presence,
        lambda message: CommandResult(
            ok=True,
            result={"method": message["method"], "params": message["params"]},
        ),
    )
    browser = ChromeBrowser(tenant_id=_TENANT, user_id=user_id, chat_session_id=chat_id)
    result = browser.call("snapshot", {"tab": "1"}, timeout_seconds=10)
    thread.join()
    assert result == {"method": "snapshot", "params": {"tab": "1"}}


def test_a_refusal_reaches_the_model_as_a_tool_error() -> None:
    user_id, chat_id, presence = _shared_chat()
    _extension(
        user_id,
        presence,
        lambda _message: CommandResult(
            ok=False, error=CommandError(message="The user is using this tab.")
        ),
    )
    browser = ChromeBrowser(tenant_id=_TENANT, user_id=user_id, chat_session_id=chat_id)
    with pytest.raises(ToolCallException) as raised:
        browser.call("act", {"action": "click"}, timeout_seconds=10)
    assert raised.value.llm_facing_message == "The user is using this tab."


def test_a_lost_extension_gives_an_unknown_outcome_at_once() -> None:
    user_id, chat_id, presence = _shared_chat()
    browser = ChromeBrowser(tenant_id=_TENANT, user_id=user_id, chat_session_id=chat_id)
    threading.Timer(1, lambda: relay.drop_presence(_TENANT, user_id, presence)).start()
    started = time.monotonic()
    with pytest.raises(ToolCallException) as raised:
        browser.call("act", {"action": "click"}, timeout_seconds=30)
    assert raised.value.llm_facing_message == relay.LOST_MESSAGE
    assert time.monotonic() - started < 10


def test_calls_need_the_chats_grant_and_a_connected_chrome() -> None:
    user_id, chat_id, presence = _shared_chat()
    other_chat = ChromeBrowser(
        tenant_id=_TENANT, user_id=user_id, chat_session_id=uuid4()
    )
    with pytest.raises(ToolCallException) as raised:
        other_chat.call("status", {}, timeout_seconds=5)
    assert raised.value.llm_facing_message == relay.NO_GRANT_MESSAGE

    other_user = ChromeBrowser(
        tenant_id=_TENANT, user_id=uuid4(), chat_session_id=chat_id
    )
    with pytest.raises(ToolCallException) as raised:
        other_user.call("status", {}, timeout_seconds=5)
    assert raised.value.llm_facing_message == relay.NO_GRANT_MESSAGE

    relay.drop_presence(_TENANT, user_id, presence)
    browser = ChromeBrowser(tenant_id=_TENANT, user_id=user_id, chat_session_id=chat_id)
    with pytest.raises(ToolCallException) as raised:
        browser.call("status", {}, timeout_seconds=5)
    assert raised.value.llm_facing_message == relay.NOT_CONNECTED_MESSAGE


def test_a_cancel_ends_the_wait() -> None:
    user_id, chat_id, _presence = _shared_chat()
    browser = ChromeBrowser(tenant_id=_TENANT, user_id=user_id, chat_session_id=chat_id)
    signal = CancellationSignal()
    threading.Timer(1, signal.cancel).start()
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        browser.call("status", {}, timeout_seconds=30)
    # The queued command never reaches the extension.
    assert relay.pop_message(_TENANT, user_id, _presence.installation_id) is None


def test_a_command_past_its_deadline_is_dropped(cache: CacheBackend) -> None:
    user_id, installation_id = uuid4(), uuid4()
    cache.rpush(
        relay.commands_key(user_id, installation_id),
        json.dumps({"type": "command", "deadline": time.time() - 1}),
    )
    assert relay.pop_message(_TENANT, user_id, installation_id) is None


def test_a_newer_connection_takes_the_installation_over() -> None:
    user_id = uuid4()
    first = Presence(
        installation_id=uuid4(), connection_id="old", label="Chrome", version="1.3"
    )
    relay.claim_presence(_TENANT, user_id, first)
    newer = first.model_copy(update={"connection_id": "new"})
    relay.claim_presence(_TENANT, user_id, newer)
    assert not relay.renew_presence(_TENANT, user_id, first)
    assert relay.renew_presence(_TENANT, user_id, newer)
    # The old connection's close leaves the newer presence alone.
    relay.drop_presence(_TENANT, user_id, first)
    assert relay.is_connected(_TENANT, user_id, first.installation_id)
