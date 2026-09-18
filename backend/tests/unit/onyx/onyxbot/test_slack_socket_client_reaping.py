"""Tests for closing Slack socket clients whose bot row was deleted."""

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.onyxbot.slack.listener import SlackbotHandler, prefilter_requests

_LISTENER = "onyx.onyxbot.slack.listener"

_TENANT = "tenant_aaaaaaaa-0000-0000-0000-000000000000"
_OTHER_TENANT = "tenant_bbbbbbbb-0000-0000-0000-000000000000"


def _make_handler(
    pairs: list[tuple[str, int]],
) -> tuple[SlackbotHandler, dict[tuple[str, int], MagicMock]]:
    """Build a handler without __init__, which starts threads and a metrics server."""
    handler = object.__new__(SlackbotHandler)
    handler.tenant_ids = {tenant_id for tenant_id, _ in pairs}
    handler.socket_clients = {}
    handler.slack_bot_tokens = {}

    clients: dict[tuple[str, int], MagicMock] = {}
    for pair in pairs:
        client = MagicMock()
        clients[pair] = client
        handler.socket_clients[pair] = client
        handler.slack_bot_tokens[pair] = MagicMock()
    return handler, clients


def test_closes_client_for_deleted_bot_and_keeps_live_one() -> None:
    handler, clients = _make_handler([(_TENANT, 3), (_TENANT, 4)])

    handler._close_bot_clients(tenant_id=_TENANT, live_bot_ids={4})

    assert (_TENANT, 3) not in handler.socket_clients
    assert (_TENANT, 3) not in handler.slack_bot_tokens
    clients[(_TENANT, 3)].close.assert_called_once()

    assert (_TENANT, 4) in handler.socket_clients
    assert (_TENANT, 4) in handler.slack_bot_tokens
    clients[(_TENANT, 4)].close.assert_not_called()


def test_leaves_other_tenants_alone() -> None:
    handler, clients = _make_handler([(_TENANT, 3), (_OTHER_TENANT, 3)])

    handler._close_bot_clients(tenant_id=_TENANT, live_bot_ids=set())

    assert (_OTHER_TENANT, 3) in handler.socket_clients
    clients[(_OTHER_TENANT, 3)].close.assert_not_called()


def test_forgets_client_even_if_close_fails() -> None:
    handler, clients = _make_handler([(_TENANT, 3)])
    clients[(_TENANT, 3)].close.side_effect = RuntimeError("socket already gone")

    handler._close_bot_clients(tenant_id=_TENANT, live_bot_ids={4})

    # A close that fails must not leave the client behind to keep taking events.
    assert handler.socket_clients == {}
    assert handler.slack_bot_tokens == {}


def test_drops_tokens_left_without_a_client() -> None:
    handler, _ = _make_handler([])
    handler.tenant_ids = {_TENANT}
    # start_socket_client can fail after the tokens entry is written.
    handler.slack_bot_tokens[(_TENANT, 3)] = MagicMock()

    handler._close_bot_clients(tenant_id=_TENANT, live_bot_ids=set())

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


def test_prefilter_skips_request_when_bot_row_is_gone() -> None:
    """A deleted bot's socket can still deliver events, so prefilter skips them."""

    @contextmanager
    def _fake_session() -> Any:
        yield MagicMock()

    client = MagicMock()
    client.slack_bot_id = 3
    req = MagicMock()
    req.type = "events_api"
    req.payload = {"event": {"type": "app_mention", "channel": "C123"}}

    with (
        patch(f"{_LISTENER}.get_current_tenant_id", return_value=_TENANT),
        patch(f"{_LISTENER}.get_onyx_bot_auth_ids", return_value=("U123", "B123")),
        patch(f"{_LISTENER}.get_session_with_current_tenant", _fake_session),
        patch(f"{_LISTENER}.fetch_slack_bot_or_none", return_value=None),
    ):
        assert prefilter_requests(req, client) is False
