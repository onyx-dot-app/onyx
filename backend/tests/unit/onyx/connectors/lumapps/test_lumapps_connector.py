from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.lumapps.connector import _parse_dt
from onyx.connectors.lumapps.connector import LumAppsConnector
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument


def _make_connector(list_response: dict[str, Any]) -> LumAppsConnector:
    connector = LumAppsConnector(
        base_url="https://example.cell.lumapps.com",
        organization_id="org-1",
    )
    client = MagicMock()
    client.list_content.return_value = list_response
    connector._client = client
    return connector


def _item(content_id: str, status: str, updated_at: str) -> dict[str, Any]:
    return {
        "id": content_id,
        "status": status,
        "title": f"Title {content_id}",
        "updatedAt": updated_at,
        "template": None,
        "properties": None,
        "metadata": [],
    }


def test_load_from_checkpoint_yields_only_live_content() -> None:
    """Non-LIVE items must be skipped even if the API-side status filter
    fails to apply (defense in depth)."""
    connector = _make_connector(
        {
            "items": [
                _item("live-1", "LIVE", "2026-07-01T12:00:00Z"),
                _item("draft-1", "DRAFT", "2026-07-01T11:00:00Z"),
                _item("archive-1", "ARCHIVE", "2026-07-01T10:00:00Z"),
                _item("live-2", "live", "2026-07-01T09:00:00Z"),  # case-insensitive
            ],
            "more": False,
        }
    )

    start = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 7, 2, tzinfo=timezone.utc).timestamp()
    results = list(
        connector.load_from_checkpoint(start, end, connector.build_dummy_checkpoint())
    )

    docs = [r for r in results if isinstance(r, Document)]
    assert [d.id for d in docs] == ["live-1", "live-2"]


def test_slim_docs_exclude_non_live_content() -> None:
    """Pruning enumeration must exclude non-LIVE items so content leaving
    LIVE gets pruned from the index."""
    connector = _make_connector(
        {
            "items": [
                {"id": "live-1", "status": "LIVE"},
                {"id": "draft-1", "status": "DRAFT"},
                {"id": "no-status"},
            ],
            "more": False,
        }
    )

    batches = list(connector.retrieve_all_slim_docs())

    assert len(batches) == 1
    assert [doc.id for doc in batches[0] if isinstance(doc, SlimDocument)] == ["live-1"]
    assert all(isinstance(doc, SlimDocument) for doc in batches[0])


def test_slim_docs_use_uid_fallback_like_indexing() -> None:
    """An item with only a uid is indexed under that uid, so the slim set must
    carry it too — otherwise pruning would delete a live document."""
    connector = _make_connector(
        {
            "items": [
                {"id": "live-1", "status": "LIVE"},
                {"uid": "uid-only-1", "status": "LIVE"},
            ],
            "more": False,
        }
    )

    batches = list(connector.retrieve_all_slim_docs())

    assert [doc.id for doc in batches[0] if isinstance(doc, SlimDocument)] == [
        "live-1",
        "uid-only-1",
    ]


def test_http_base_url_is_rejected() -> None:
    """The client sends credentials on every token request; plain http would
    leak them in transit."""
    connector = LumAppsConnector(
        base_url="http://example.cell.lumapps.com",
        organization_id="org-1",
    )
    connector.load_credentials(
        {
            "lumapps_application_id": "app",
            "lumapps_api_key": "key",
            "lumapps_service_user": "svc@example.com",
        }
    )
    with pytest.raises(ConnectorValidationError, match="https"):
        connector.validate_connector_settings()


def test_list_body_requests_live_status_from_api() -> None:
    """The API-side filter stays in place alongside the in-code check."""
    connector = _make_connector({"items": [], "more": False})
    assert connector._list_body()["status"] == ["LIVE"]


def test_parse_dt_handles_iso_and_epoch() -> None:
    """updatedAt drives the incremental early-break; both ISO-8601 and numeric
    epochs (seconds or milliseconds) must parse to the same instant so an
    unexpected format doesn't silently force a full re-scan."""
    expected = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    iso = _parse_dt("2026-07-01T12:00:00Z")
    epoch_s = _parse_dt(int(expected.timestamp()))
    epoch_ms = _parse_dt(int(expected.timestamp()) * 1000)
    epoch_str = _parse_dt(str(int(expected.timestamp())))

    assert iso == expected
    assert epoch_s == expected
    assert epoch_ms == expected
    assert epoch_str == expected

    # Unparseable / non-timestamp values are ignored (never crash the walk).
    assert _parse_dt("not-a-date") is None
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _parse_dt(True) is None
