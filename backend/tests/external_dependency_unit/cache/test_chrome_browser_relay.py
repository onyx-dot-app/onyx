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
from onyx.browser_extension.models import (
    CommandError,
    CommandResult,
    GrantReport,
    GrantTab,
    Presence,
)
from onyx.browser_extension.relay import ChromeBrowser
from onyx.cache.interface import CacheBackend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.tools.models import ToolCallException

_TENANT = "public"


@pytest.fixture(autouse=True)
def _use_cache(cache: CacheBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relay, "_cache", lambda _tenant_id: cache)


def _connect(user_id: UUID, installation_id: UUID | None = None) -> Presence:
    presence = Presence(
        installation_id=installation_id or uuid4(),
        connection_id=uuid4().hex,
        label="Chrome",
        version="1.3",
    )
    relay.claim_presence(_TENANT, user_id, presence)
    return presence


def _share(user_id: UUID, chat_id: UUID, presence: Presence) -> None:
    """A turn binds the chat; the extension reports the active tab."""
    relay.bind_chat(
        _TENANT,
        user_id,
        chat_id,
        presence,
        chat_title="Chat",
        window_id=7,
        tab_id=1,
        side_panel=True,
    )
    # Skip an earlier end_grant for a chat that moved away.
    message = relay.pop_message(_TENANT, user_id, presence)
    while message is not None and message["type"] != "bind":
        message = relay.pop_message(_TENANT, user_id, presence)
    assert message is not None
    grant = relay.save_grant(
        _TENANT,
        user_id,
        presence.installation_id,
        GrantReport(
            chat_session_id=chat_id,
            tabs=[
                GrantTab(
                    id="1",
                    title="Wiki",
                    url="https://wiki.example/",
                    origin="https://wiki.example",
                )
            ],
            current="1",
        ),
    )
    assert grant is not None


def _browser(user_id: UUID, chat_id: UUID, response_id: int = 1) -> ChromeBrowser:
    return ChromeBrowser(
        tenant_id=_TENANT,
        user_id=user_id,
        chat_session_id=chat_id,
        response_id=response_id,
    )


def _shared_chat() -> tuple[UUID, UUID, Presence]:
    """A user whose connected Chrome shares a tab with a new chat."""
    user_id, chat_id = uuid4(), uuid4()
    presence = _connect(user_id)
    _share(user_id, chat_id, presence)
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
            message = relay.pop_message(_TENANT, user_id, presence)
            if message is not None and message["type"] == "command":
                relay.push_result(_TENANT, str(message["command_id"]), answer(message))
                return

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _after_command(
    user_id: UUID, presence: Presence, then: Callable[[], object]
) -> threading.Thread:
    """Takes the first command off the connection's list, as the extension
    does, then runs `then` instead of answering."""

    def run() -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            message = relay.pop_message(_TENANT, user_id, presence)
            if message is not None and message["type"] == "command":
                then()
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
    browser = _browser(user_id, chat_id)
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
    browser = _browser(user_id, chat_id)
    with pytest.raises(ToolCallException) as raised:
        browser.call("act", {"action": "click"}, timeout_seconds=10)
    assert raised.value.llm_facing_message == "The user is using this tab."


def test_a_lost_extension_gives_an_unknown_outcome_at_once() -> None:
    user_id, chat_id, presence = _shared_chat()
    browser = _browser(user_id, chat_id)
    _after_command(
        user_id, presence, lambda: relay.drop_presence(_TENANT, user_id, presence)
    )
    started = time.monotonic()
    with pytest.raises(ToolCallException) as raised:
        browser.call("act", {"action": "click"}, timeout_seconds=30)
    assert raised.value.llm_facing_message == relay.LOST_MESSAGE
    assert time.monotonic() - started < 10


def test_calls_need_the_chats_grant_and_a_connected_chrome() -> None:
    user_id, chat_id, presence = _shared_chat()
    other_chat = _browser(user_id, uuid4())
    with pytest.raises(ToolCallException) as raised:
        other_chat.call("status", {}, timeout_seconds=5)
    assert raised.value.llm_facing_message == relay.NO_GRANT_MESSAGE

    other_user = _browser(uuid4(), chat_id)
    with pytest.raises(ToolCallException) as raised:
        other_user.call("status", {}, timeout_seconds=5)
    assert raised.value.llm_facing_message == relay.NO_GRANT_MESSAGE

    relay.drop_presence(_TENANT, user_id, presence)
    browser = _browser(user_id, chat_id)
    with pytest.raises(ToolCallException) as raised:
        browser.call("status", {}, timeout_seconds=5)
    assert raised.value.llm_facing_message == relay.NOT_CONNECTED_MESSAGE


def test_a_cancel_ends_the_wait() -> None:
    user_id, chat_id, _presence = _shared_chat()
    browser = _browser(user_id, chat_id)
    signal = CancellationSignal()
    threading.Timer(1, signal.cancel).start()
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        browser.call("status", {}, timeout_seconds=30)
    # The queued command never reaches the extension.
    assert relay.pop_message(_TENANT, user_id, _presence) is None


def test_a_command_past_its_deadline_is_dropped(cache: CacheBackend) -> None:
    user_id = uuid4()
    presence = _connect(user_id)
    cache.rpush(
        relay.commands_key(user_id, presence.installation_id, presence.connection_id),
        json.dumps({"type": "command", "deadline": time.time() - 1}),
    )
    assert relay.pop_message(_TENANT, user_id, presence) is None


def test_an_unread_message_list_expires(cache: CacheBackend) -> None:
    if isinstance(cache, PostgresCacheBackend):
        pytest.skip("Postgres list items expire one by one on their own.")
    user_id, chat_id, presence = _shared_chat()
    relay.end_grant(_TENANT, user_id, chat_id, notify=True)
    key = relay.commands_key(user_id, presence.installation_id, presence.connection_id)
    assert 0 < cache.ttl(key) <= relay.REQUEST_SECONDS


def test_a_newer_connection_takes_the_installation_over() -> None:
    user_id = uuid4()
    first = _connect(user_id)
    newer = _connect(user_id, first.installation_id)
    assert not relay.owns_presence(_TENANT, user_id, first)
    assert not relay.renew_presence(_TENANT, user_id, first)
    assert relay.renew_presence(_TENANT, user_id, newer)
    # Messages go to the newer connection only.
    relay.bind_chat(
        _TENANT,
        user_id,
        uuid4(),
        newer,
        chat_title="Chat",
        window_id=None,
        tab_id=None,
        side_panel=False,
    )
    assert relay.pop_message(_TENANT, user_id, first) is None
    message = relay.pop_message(_TENANT, user_id, newer)
    assert message is not None and message["type"] == "bind"
    # The old connection's close leaves the newer presence alone.
    relay.drop_presence(_TENANT, user_id, first)
    assert relay.owns_presence(_TENANT, user_id, newer)
    assert [
        p.connection_id for p in relay.connected_installations(_TENANT, user_id)
    ] == [newer.connection_id]


def test_a_takeover_loses_the_command_at_once() -> None:
    user_id, chat_id, presence = _shared_chat()
    browser = _browser(user_id, chat_id)
    _after_command(
        user_id, presence, lambda: _connect(user_id, presence.installation_id)
    )
    started = time.monotonic()
    with pytest.raises(ToolCallException) as raised:
        browser.call("act", {"action": "click"}, timeout_seconds=30)
    assert raised.value.llm_facing_message == relay.LOST_MESSAGE
    assert time.monotonic() - started < 10


def test_a_ping_keeps_the_installation_listed(cache: CacheBackend) -> None:
    user_id = uuid4()
    presence = _connect(user_id)
    # The list lapsed (it lives a day); the live socket's ping restores it.
    cache.set_remove(relay._installations_key(user_id), str(presence.installation_id))
    assert relay.connected_installations(_TENANT, user_id) == []
    assert relay.renew_presence(_TENANT, user_id, presence)
    assert relay.connected_installations(_TENANT, user_id) == [presence]


def test_a_chat_that_moved_keeps_its_grant() -> None:
    """Chat X moves from installation A to B; A's next share leaves X's grant
    with B alone."""
    user_id, chat_x, chat_y = uuid4(), uuid4(), uuid4()
    work, home = _connect(user_id), _connect(user_id)
    _share(user_id, chat_x, work)
    _share(user_id, chat_x, home)
    _share(user_id, chat_y, work)
    grant = relay.load_grant(_TENANT, chat_x, user_id)
    assert grant is not None and grant.installation_id == home.installation_id
    assert relay.load_grant(_TENANT, chat_y, user_id) is not None


def test_a_stop_from_another_installation_leaves_the_grant() -> None:
    """Chat X moved from installation A to B; A's late stop of X leaves B's
    grant alone."""
    user_id, chat_x = uuid4(), uuid4()
    work, home = _connect(user_id), _connect(user_id)
    _share(user_id, chat_x, work)
    _share(user_id, chat_x, home)
    relay.end_grant(
        _TENANT, user_id, chat_x, notify=False, installation_id=work.installation_id
    )
    assert relay.load_grant(_TENANT, chat_x, user_id) is not None
    relay.end_grant(
        _TENANT, user_id, chat_x, notify=False, installation_id=home.installation_id
    )
    assert relay.load_grant(_TENANT, chat_x, user_id) is None


def test_a_replaced_connection_cannot_renew_over_the_newer_one() -> None:
    user_id = uuid4()
    first = _connect(user_id)
    newer = _connect(user_id, first.installation_id)
    assert not relay.renew_presence(_TENANT, user_id, first)
    assert relay.owns_presence(_TENANT, user_id, newer)
    # A lapsed presence goes to the first connection that renews it.
    relay.drop_presence(_TENANT, user_id, newer)
    assert relay.renew_presence(_TENANT, user_id, first)


def _bind(
    user_id: UUID,
    chat_id: UUID,
    presence: Presence,
    *,
    tab_id: int | None = 1,
    side_panel: bool = True,
) -> None:
    relay.bind_chat(
        _TENANT,
        user_id,
        chat_id,
        presence,
        chat_title="Chat",
        window_id=7,
        tab_id=tab_id,
        side_panel=side_panel,
    )


def test_a_bind_stores_the_grant_and_tells_the_extension() -> None:
    user_id, chat_id = uuid4(), uuid4()
    presence = _connect(user_id)
    _bind(user_id, chat_id, presence)
    grant = relay.load_grant(_TENANT, chat_id, user_id)
    assert grant is not None
    assert grant.side_panel and grant.window_id == 7
    assert grant.current == "1" and [tab.id for tab in grant.tabs] == ["1"]
    message = relay.pop_message(_TENANT, user_id, presence)
    assert message is not None
    assert message["type"] == "bind"
    assert message["chat_session_id"] == str(chat_id)
    assert message["window_id"] == 7 and message["tab_id"] == 1
    assert message["side_panel"] is True


def test_a_main_chat_bind_starts_without_a_tab() -> None:
    user_id, chat_id = uuid4(), uuid4()
    presence = _connect(user_id)
    _bind(user_id, chat_id, presence, tab_id=None, side_panel=False)
    grant = relay.load_grant(_TENANT, chat_id, user_id)
    assert grant is not None and grant.tabs == [] and grant.current is None
    # An empty report does not end the grant.
    saved = relay.save_grant(
        _TENANT,
        user_id,
        presence.installation_id,
        GrantReport(chat_session_id=chat_id, tabs=[], current=None),
    )
    assert saved is not None


def test_a_rebind_of_the_same_chat_keeps_its_tabs_and_sites() -> None:
    user_id, chat_id, presence = _shared_chat()
    browser = _browser(user_id, chat_id)
    browser._record_once("https://once.example")
    _bind(user_id, chat_id, presence, tab_id=None, side_panel=False)
    grant = relay.load_grant(_TENANT, chat_id, user_id)
    assert grant is not None
    assert grant.tabs[0].origin == "https://wiki.example"
    assert grant.once_origins == ["https://once.example"]
    assert not grant.side_panel


def test_a_bind_of_another_chat_ends_the_installations_old_grant() -> None:
    user_id, chat_x, chat_y = uuid4(), uuid4(), uuid4()
    presence = _connect(user_id)
    _bind(user_id, chat_x, presence)
    _bind(user_id, chat_y, presence)
    assert relay.load_grant(_TENANT, chat_x, user_id) is None
    assert relay.load_grant(_TENANT, chat_y, user_id) is not None
    # The old chat's end is not sent; the extension replaces its grant.
    types = []
    while (message := relay.pop_message(_TENANT, user_id, presence)) is not None:
        types.append(message["type"])
    assert types == ["bind", "bind"]


def test_a_bind_of_a_chat_on_another_installation_notifies_the_old_one() -> None:
    user_id, chat_id = uuid4(), uuid4()
    work, home = _connect(user_id), _connect(user_id)
    _bind(user_id, chat_id, work)
    _bind(user_id, chat_id, home)
    grant = relay.load_grant(_TENANT, chat_id, user_id)
    assert grant is not None and grant.installation_id == home.installation_id
    types = []
    while (message := relay.pop_message(_TENANT, user_id, work)) is not None:
        types.append(message["type"])
    assert types == ["bind", "end_grant"]


def test_a_tab_report_only_updates_the_holders_grant() -> None:
    user_id, chat_id, presence = _shared_chat()
    report = GrantReport(
        chat_session_id=chat_id,
        tabs=[GrantTab(id="2", origin="https://b.example")],
        current="2",
    )
    other = _connect(user_id)
    assert relay.save_grant(_TENANT, user_id, other.installation_id, report) is None
    saved = relay.save_grant(_TENANT, user_id, presence.installation_id, report)
    assert saved is not None and saved.current == "2"
    nobody = report.model_copy(update={"chat_session_id": uuid4()})
    assert relay.save_grant(_TENANT, user_id, presence.installation_id, nobody) is None


def test_a_new_site_asks_for_approval() -> None:
    user_id, chat_id, _presence = _shared_chat()
    details = _browser(user_id, chat_id).site_approval(
        "open", {"url": "Docs.Example.com/page"}
    )
    assert details is not None
    assert details.action_id == "onyx:chrome.site:https://docs.example.com"
    assert details.payload == {"site": "https://docs.example.com"}
    assert details.display_name == "Use docs.example.com in your Chrome"


def test_a_site_approved_once_holds_for_the_same_response_only() -> None:
    user_id, chat_id, _presence = _shared_chat()
    browser = _browser(user_id, chat_id, response_id=5)
    params: dict[str, JsonValue] = {"url": "https://new.example/a"}
    assert browser.site_approval("navigate", params) is not None
    browser._record_once("https://new.example")
    assert browser.site_approval("navigate", params) is None
    assert (
        _browser(user_id, chat_id, response_id=6).site_approval("navigate", params)
        is not None
    )


def test_a_tab_action_uses_the_origin_the_tab_reported() -> None:
    user_id, chat_id, _presence = _shared_chat()
    browser = _browser(user_id, chat_id)
    # The reported tab is on a site that nobody approved.
    assert browser.site_approval("act", {"tab": "1", "action": "click"}) is not None
    assert browser.site_approval("act", {"action": "click"}) is not None
    browser._record_once("https://wiki.example")
    assert browser.site_approval("act", {"tab": "1", "action": "click"}) is None


def test_an_unknown_origin_needs_no_approval() -> None:
    user_id, chat_id, _presence = _shared_chat()
    browser = _browser(user_id, chat_id)
    assert browser.site_approval("act", {"tab": "9", "action": "click"}) is None
    assert browser.site_approval("open", {"url": "ftp://files.example"}) is None
    assert browser.site_approval("status", {}) is not None
    assert _browser(user_id, uuid4()).site_approval("status", {}) is None


def test_a_call_records_its_site_and_sends_the_allowed_sites() -> None:
    user_id, chat_id, presence = _shared_chat()
    seen: list[dict[str, JsonValue]] = []

    def answer(message: dict[str, JsonValue]) -> CommandResult:
        seen.append(message)
        return CommandResult(ok=True, result={})

    thread = _extension(user_id, presence, answer)
    browser = _browser(user_id, chat_id, response_id=3)
    browser.call("navigate", {"url": "https://new.example/x"}, timeout_seconds=10)
    thread.join()
    assert seen[0]["origins"] == ["https://new.example"]
    grant = relay.load_grant(_TENANT, chat_id, user_id)
    assert grant is not None
    assert grant.once_origins == ["https://new.example"]
    assert grant.once_response_id == 3
    # A later response starts the list again.
    browser_next = _browser(user_id, chat_id, response_id=4)
    browser_next._record_once("https://other.example")
    grant = relay.load_grant(_TENANT, chat_id, user_id)
    assert grant is not None and grant.once_origins == ["https://other.example"]
