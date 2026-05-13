"""Unit tests for the Freshdesk connector's pagination window-rolling.

Freshdesk's ``/api/v2/tickets`` endpoint hard-caps pagination at 300 pages
and returns 400 for ``page >= 301``. To get past that on accounts with
more than ``per_page * 300`` matching tickets, the connector restarts at
page 1 with ``updated_since`` advanced to the last fetched ticket's
``updated_at``.

These tests patch the page cap and per-page constants down to small
values so we don't have to mock 300 HTTP responses.
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.freshdesk import connector as freshdesk_connector
from onyx.connectors.freshdesk.connector import FreshdeskConnector


def _fake_response(status_code: int, payload: list[dict[str, Any]]) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = json.dumps(payload).encode()
    response.raise_for_status = MagicMock()
    return response


def _ticket(ticket_id: int, updated_at: str) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "subject": f"Ticket {ticket_id}",
        "description_text": "...",
        "status": 2,
        "priority": 1,
        "source": 2,
        "updated_at": updated_at,
    }


class TestPaginationWindowRoll:
    def test_rolls_updated_since_window_when_hitting_page_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Patch the cap and per-page down so we can exercise the rollover
        # without having to mock 300 pages of responses.
        monkeypatch.setattr(freshdesk_connector, "_FRESHDESK_MAX_PAGE", 2)
        monkeypatch.setattr(freshdesk_connector, "_FRESHDESK_PER_PAGE", 2)

        last_updated_at_on_page_2 = "2024-01-02T11:00:00Z"

        # Page 1 — full page (== per_page), pagination continues.
        page_1 = [
            _ticket(1, "2024-01-01T10:00:00Z"),
            _ticket(2, "2024-01-01T11:00:00Z"),
        ]
        # Page 2 — full page, hits the (patched) cap, triggering a window roll.
        page_2 = [
            _ticket(3, "2024-01-02T10:00:00Z"),
            _ticket(4, last_updated_at_on_page_2),
        ]
        # First page of the new window — partial page, pagination ends.
        page_3 = [_ticket(5, "2024-01-02T11:30:00Z")]

        responses = iter(
            [
                _fake_response(200, page_1),
                _fake_response(200, page_2),
                _fake_response(200, page_3),
            ]
        )
        captured_params: list[dict[str, Any]] = []

        def fake_get(url: str, auth: tuple, params: dict) -> Any:  # noqa: ARG001
            captured_params.append(dict(params))
            return next(responses)

        monkeypatch.setattr(
            freshdesk_connector, "_rate_limited_freshdesk_get", fake_get
        )

        connector = FreshdeskConnector()
        # Bypass load_credentials — the rate-limited GET is mocked, so the
        # values don't have to be real.
        connector.api_key = "fake-key"
        connector.domain = "example"

        all_tickets = [t for batch in connector._fetch_tickets() for t in batch]

        assert [t["id"] for t in all_tickets] == [1, 2, 3, 4, 5]
        assert len(captured_params) == 3

        # Call 1: page 1 of the original window, no updated_since (start=None),
        # and our new sort params are present.
        assert captured_params[0]["page"] == 1
        assert "updated_since" not in captured_params[0]
        assert captured_params[0]["per_page"] == 2
        assert captured_params[0]["order_by"] == "updated_at"
        assert captured_params[0]["order_type"] == "asc"

        # Call 2: page 2 — still in the original window.
        assert captured_params[1]["page"] == 2
        assert "updated_since" not in captured_params[1]

        # Call 3: page reset to 1, updated_since advanced to the last ticket's
        # updated_at from the page that hit the cap.
        assert captured_params[2]["page"] == 1
        assert captured_params[2]["updated_since"] == last_updated_at_on_page_2
