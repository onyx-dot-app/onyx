"""Freshdesk's ``/api/v2/tickets`` endpoint returns only tickets created in
the last 30 days unless the request sets ``updated_since``. A full load (and
pruning, which uses ``load_from_state``) must set it, or every older ticket
looks deleted at the source."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.freshdesk import connector as freshdesk_connector
from onyx.connectors.freshdesk.connector import FreshdeskConnector


def test_load_from_state_requests_tickets_older_than_30_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_params: list[dict[str, Any]] = []

    def fake_get(url: str, auth: tuple, params: dict) -> Any:  # noqa: ARG001
        captured_params.append(dict(params))
        response = MagicMock()
        response.status_code = 200
        response.content = json.dumps([]).encode()
        return response

    monkeypatch.setattr(freshdesk_connector, "_rate_limited_freshdesk_get", fake_get)

    connector = FreshdeskConnector()
    connector.api_key = "fake-key"
    connector.domain = "example"

    assert list(connector.load_from_state()) == []

    assert len(captured_params) == 1
    assert captured_params[0]["updated_since"] == "1970-01-01T00:00:00+00:00"
