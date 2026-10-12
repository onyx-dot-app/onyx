"""Tests for the lifecycle of Slack socket clients: stale bots, failed starts, prefilter."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from onyx.onyxbot.slack.listener import SlackbotHandler, prefilter_requests
from onyx.server.manage.models import SlackBotTokens

_LISTENER = "onyx.onyxbot.slack.listener"

_TENANT = "tenant_aaaaaaaa-0000-0000-0000-000000000000"
_OTHER_TENANT = "tenant_bbbbbbbb-0000-0000-0000-000000000000"


@contextmanager
def _fake_session() -> Iterator[MagicMock]:
    yield MagicMock()


def _make_handler(
    pairs: list[tuple[str, int]],
) -> tuple[SlackbotHandler, dict[tuple[str, int], MagicMock]]:
    """Build a handler without __init__, which starts threads and a metrics server."""
    handler = object.__new__(SlackbotHandler)
    handler.tenant_ids = {tenant_id for tenant_id, _ in pairs}
    handler.socket_clients = {}
    handler.slack_bot_tokens = {}
    handler.redis_locks = {}

    clients: dict[tuple[str, int], MagicMock] = {}
    for pair in pairs:
        client = MagicMock()
        clients[pair] = client
        handler.socket_clients[pair] = client
        handler.slack_bot_tokens[pair] = MagicMock()
    return handler, clients


def _bot_with_tokens(bot_token: str, app_token: str) -> MagicMock:
    bot = MagicMock()
    bot.id = 4
    bot.bot_token.get_value.return_value = bot_token
    bot.app_token.get_value.return_value = app_token
    return bot


def test_acquire_tenants_drops_the_client_of_a_deleted_bot() -> None:
    """The tenant still has a bot, so `_remove_tenant` never runs for it."""
    handler, clients = _make_handler([(_TENANT, 3), (_TENANT, 4)])
    live_bot = MagicMock()
    live_bot.id = 4

    with (
        patch(
            f"{_LISTENER}.fetch_ee_implementation_or_noop", return_value=lambda: set()
        ),
        patch(f"{_LISTENER}.get_all_tenant_ids", return_value=[_TENANT]),
        patch(f"{_LISTENER}.get_redis_client"),
        patch(f"{_LISTENER}.get_session_with_current_tenant", _fake_session),
        patch(f"{_LISTENER}.fetch_slack_bots", return_value=[live_bot]),
        patch.object(SlackbotHandler, "_manage_clients_per_tenant"),
    ):
        handler.acquire_tenants()

    clients[(_TENANT, 3)].close.assert_called_once()
    assert (_TENANT, 3) not in handler.socket_clients
    assert (_TENANT, 4) in handler.socket_clients
    assert _TENANT in handler.tenant_ids


def test_drops_deleted_bot_and_keeps_live_one() -> None:
    handler, clients = _make_handler([(_TENANT, 3), (_TENANT, 4)])

    handler._drop_stale_bots(tenant_id=_TENANT, live_bot_ids={4})

    assert (_TENANT, 3) not in handler.socket_clients
    assert (_TENANT, 3) not in handler.slack_bot_tokens
    clients[(_TENANT, 3)].close.assert_called_once()

    assert (_TENANT, 4) in handler.socket_clients
    assert (_TENANT, 4) in handler.slack_bot_tokens
    clients[(_TENANT, 4)].close.assert_not_called()


def test_leaves_other_tenants_alone() -> None:
    handler, clients = _make_handler([(_TENANT, 3), (_OTHER_TENANT, 3)])

    handler._drop_stale_bots(tenant_id=_TENANT, live_bot_ids=set())

    assert (_OTHER_TENANT, 3) in handler.socket_clients
    clients[(_OTHER_TENANT, 3)].close.assert_not_called()


def test_failed_close_stops_the_workers_close_would_have_stopped() -> None:
    handler, clients = _make_handler([(_TENANT, 3)])
    client = clients[(_TENANT, 3)]
    client.close.side_effect = RuntimeError("socket already gone")

    handler._drop_stale_bots(tenant_id=_TENANT, live_bot_ids={4})

    assert handler.socket_clients == {}
    assert handler.slack_bot_tokens == {}
    # close() stops these after disconnecting, so a raised disconnect skips them.
    client.current_app_monitor.shutdown.assert_called_once()
    client.message_processor.shutdown.assert_called_once()
    client.message_workers.shutdown.assert_called_once()


def test_worker_shutdown_failure_does_not_escape() -> None:
    handler, clients = _make_handler([(_TENANT, 3)])
    client = clients[(_TENANT, 3)]
    client.close.side_effect = RuntimeError("socket already gone")
    client.message_processor.shutdown.side_effect = RuntimeError("thread already dead")

    handler._drop_stale_bots(tenant_id=_TENANT, live_bot_ids={4})

    assert handler.socket_clients == {}
    client.message_workers.shutdown.assert_called_once()


def test_drops_tokens_left_without_a_client() -> None:
    handler, _ = _make_handler([])
    # start_socket_client can fail after the tokens entry is written.
    handler.slack_bot_tokens[(_TENANT, 3)] = MagicMock()

    handler._drop_stale_bots(tenant_id=_TENANT, live_bot_ids=set())

    assert handler.slack_bot_tokens == {}


def test_remove_tenant_closes_every_client_and_forgets_the_tenant() -> None:
    handler, clients = _make_handler([(_TENANT, 3), (_TENANT, 4)])
    clients[(_TENANT, 3)].close.side_effect = RuntimeError("socket already gone")

    handler._remove_tenant(_TENANT)

    # A failed close must not strand the tenant's other clients.
    assert handler.socket_clients == {}
    assert handler.slack_bot_tokens == {}
    assert _TENANT not in handler.tenant_ids
    clients[(_TENANT, 4)].close.assert_called_once()


def test_bot_without_tokens_is_dropped() -> None:
    handler, clients = _make_handler([(_TENANT, 4)])
    bot = MagicMock()
    bot.id = 4
    bot.bot_token = None

    handler._manage_clients_per_tenant(
        db_session=MagicMock(), tenant_id=_TENANT, bot=bot
    )

    clients[(_TENANT, 4)].close.assert_called_once()
    assert handler.socket_clients == {}
    assert handler.slack_bot_tokens == {}


def test_failed_start_waits_for_a_token_change() -> None:
    """A retry every cycle costs a Slack API call and a client build per failing bot."""
    handler, _ = _make_handler([])
    handler.slack_bot_tokens[(_TENANT, 4)] = SlackBotTokens(
        bot_token="xoxb-t", app_token="xapp-t"
    )

    with patch.object(SlackbotHandler, "start_socket_client") as start:
        handler._manage_clients_per_tenant(
            db_session=MagicMock(),
            tenant_id=_TENANT,
            bot=_bot_with_tokens("xoxb-t", "xapp-t"),
        )
        start.assert_not_called()

        start.return_value = MagicMock()
        handler._manage_clients_per_tenant(
            db_session=MagicMock(),
            tenant_id=_TENANT,
            bot=_bot_with_tokens("xoxb-new", "xapp-new"),
        )
        start.assert_called_once()


def test_failed_reconnect_does_not_leave_the_closed_client_mapped() -> None:
    handler, clients = _make_handler([(_TENANT, 4)])
    handler.slack_bot_tokens[(_TENANT, 4)] = SlackBotTokens(
        bot_token="xoxb-old", app_token="xapp-old"
    )

    with patch.object(SlackbotHandler, "start_socket_client", return_value=None):
        handler._manage_clients_per_tenant(
            db_session=MagicMock(),
            tenant_id=_TENANT,
            bot=_bot_with_tokens("xoxb-new", "xapp-new"),
        )

    clients[(_TENANT, 4)].close.assert_called_once()
    assert (_TENANT, 4) not in handler.socket_clients


def test_failed_auth_closes_the_client_it_built() -> None:
    """__init__ starts worker threads, so a client that is dropped needs a close."""
    built = MagicMock()
    built.web_client.auth_test.side_effect = SlackApiError(
        "invalid_auth", response=MagicMock()
    )

    with patch(f"{_LISTENER}._get_socket_client", return_value=built):
        result = SlackbotHandler.start_socket_client(
            slack_bot_id=4,
            tenant_id=_TENANT,
            slack_bot_tokens=SlackBotTokens(bot_token="xoxb-t", app_token="xapp-t"),
        )

    assert result is None
    built.close.assert_called_once()


def test_failed_connect_closes_the_client_it_built() -> None:
    built = MagicMock()
    built.web_client.auth_test.return_value = {"ok": False}
    built.connect.side_effect = SlackApiError("bad app token", response=MagicMock())

    with patch(f"{_LISTENER}._get_socket_client", return_value=built):
        result = SlackbotHandler.start_socket_client(
            slack_bot_id=4,
            tenant_id=_TENANT,
            slack_bot_tokens=SlackBotTokens(bot_token="xoxb-t", app_token="xapp-t"),
        )

    assert result is None
    built.close.assert_called_once()


def test_unexpected_connect_error_closes_the_client_and_lets_the_pass_continue() -> (
    None
):
    built = MagicMock()
    built.web_client.auth_test.return_value = {"ok": False}
    built.connect.side_effect = OSError("network unreachable")

    with patch(f"{_LISTENER}._get_socket_client", return_value=built):
        result = SlackbotHandler.start_socket_client(
            slack_bot_id=4,
            tenant_id=_TENANT,
            slack_bot_tokens=SlackBotTokens(bot_token="xoxb-t", app_token="xapp-t"),
        )

    assert result is None
    built.close.assert_called_once()


def test_shutdown_closes_every_client_after_one_close_fails() -> None:
    """The caller releases the Redis locks next, so the loop has to finish."""
    _, clients = _make_handler([(_TENANT, 3), (_OTHER_TENANT, 4)])
    clients[(_TENANT, 3)].close.side_effect = RuntimeError("socket already gone")

    SlackbotHandler.stop_socket_clients("pod-1", dict(clients))

    clients[(_OTHER_TENANT, 4)].close.assert_called_once()


def test_prefilter_skips_request_when_bot_row_is_gone() -> None:
    """A deleted bot's socket can still deliver events, so prefilter skips them."""
    client = MagicMock()
    client.slack_bot_id = 3
    req = MagicMock()
    req.type = "events_api"
    req.payload = {"event": {"type": "app_mention", "channel": "C123"}}

    with (
        patch(f"{_LISTENER}.get_current_tenant_id", return_value=_TENANT),
        patch(f"{_LISTENER}.get_onyx_bot_auth_ids") as resolve_auth_ids,
        patch(f"{_LISTENER}.get_session_with_current_tenant", _fake_session),
        patch(f"{_LISTENER}.fetch_slack_bot_or_none", return_value=None),
    ):
        assert prefilter_requests(req, client) is False

    # A cache miss there calls Slack with the deleted bot's tokens.
    resolve_auth_ids.assert_not_called()
