"""Unit tests for the JSM connector helpers.

Focuses on the parsing/normalisation edge cases that broke prior attempts at
https://github.com/onyx-dot-app/onyx/issues/2281 (negative-UTC-offset
timestamps silently failing, missing payload fields, relative URLs).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.utils import (
    build_jsm_session,
    jsm_get,
    jsm_url,
    parse_jsm_datetime,
    to_jsm_customer,
    to_jsm_request,
)
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    make_raw_request,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status.return_value = None
    return resp


class TestParseJsmDatetime:
    def test_positive_offset(self) -> None:
        dt = parse_jsm_datetime("2026-05-06T13:45:00.000+0000")
        assert dt == datetime(2026, 5, 6, 13, 45, tzinfo=timezone.utc)

    def test_negative_offset(self) -> None:
        """Regression: '-0500' suffixes previously fell through to ValueError
        and silently forced `now()` fallbacks upstream."""
        dt = parse_jsm_datetime("2026-05-06T13:45:00.000-0500")
        assert dt is not None
        assert dt == datetime(2026, 5, 6, 18, 45, tzinfo=timezone.utc)

    def test_negative_non_utc_offset_preserves_instant(self) -> None:
        # 2026-05-06T00:30:00+0530 == 2026-05-05T19:00:00Z
        dt = parse_jsm_datetime("2026-05-06T00:30:00.000+0530")
        assert dt == datetime(2026, 5, 5, 19, 0, tzinfo=timezone.utc)

    def test_z_suffix(self) -> None:
        dt = parse_jsm_datetime("2026-05-06T13:45:00Z")
        assert dt == datetime(2026, 5, 6, 13, 45, tzinfo=timezone.utc)

    def test_garbage_returns_none(self) -> None:
        assert parse_jsm_datetime("not-a-date") is None
        assert parse_jsm_datetime("") is None
        assert parse_jsm_datetime(None) is None
        assert parse_jsm_datetime(12345) is None


class TestJsmUrl:
    def test_bare_domain(self) -> None:
        session = build_jsm_session("acme.atlassian.net", "a@b.c", "tok")
        assert (
            jsm_url(session, "/request")
            == "https://acme.atlassian.net/rest/servicedeskapi/request"
        )

    def test_https_and_trailing_slash(self) -> None:
        session = build_jsm_session("https://acme.atlassian.net/", "a@b.c", "tok")
        assert (
            jsm_url(session, "/servicedesk/1")
            == "https://acme.atlassian.net/rest/servicedeskapi/servicedesk/1"
        )


class TestJsmGet:
    def test_ok(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(json_data={"ok": True})
        assert jsm_get(session, "/request", start=0) == {"ok": True}

    @pytest.mark.parametrize(
        "status_code,expected_exc",
        [
            (401, CredentialExpiredError),
            (403, InsufficientPermissionsError),
            (404, ConnectorValidationError),
        ],
    )
    def test_error_mapping(
        self, status_code: int, expected_exc: type[Exception]
    ) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status_code=status_code)
        with pytest.raises(expected_exc):
            jsm_get(session, "/request")


class TestToJsmRequest:
    def test_full_payload(self) -> None:
        raw = make_raw_request(
            participants=[
                {"accountId": "acc-2", "displayName": "Bob", "emailAddress": "b@c.d"}
            ],
            organizations=[{"id": 7, "name": "Acme Corp"}],
        )
        req = to_jsm_request(
            raw, default_service_desk_id="1", domain="acme.atlassian.net"
        )
        assert req.issue_key == "IT-1"
        assert req.request_type is not None and req.request_type.name == "Get IT help"
        assert req.status == "In Progress"
        assert req.priority == "P2"
        assert req.reporter is not None and req.reporter.display_name == "Alice"
        assert [p.display_name for p in req.participants] == ["Bob"]
        assert req.organization_ids == ["7"]
        assert req.web_url == (
            "https://acme.atlassian.net/servicedesk/customer/portal/1/IT-1"
        )

    def test_relative_web_url_absolutised_with_domain(self) -> None:
        req = to_jsm_request(
            make_raw_request(), default_service_desk_id="1", domain="acme.atlassian.net"
        )
        assert req.web_url.startswith("https://acme.atlassian.net/")

    def test_absolute_web_url_passthrough(self) -> None:
        raw = make_raw_request(web_link="https://elsewhere.example/IT-9")
        req = to_jsm_request(
            raw, default_service_desk_id="1", domain="acme.atlassian.net"
        )
        assert req.web_url == "https://elsewhere.example/IT-9"

    def test_missing_issue_key_raises(self) -> None:
        raw = make_raw_request()
        raw["issueKey"] = ""
        with pytest.raises(ValueError, match="issueKey"):
            to_jsm_request(raw)

    def test_missing_summary_raises(self) -> None:
        raw = make_raw_request()
        raw["summary"] = ""
        with pytest.raises(ValueError, match="summary"):
            to_jsm_request(raw)

    def test_missing_created_date_raises(self) -> None:
        raw = make_raw_request()
        raw["createdDate"] = {}
        with pytest.raises(ValueError, match="createdDate"):
            to_jsm_request(raw)

    def test_missing_current_status_defaults(self) -> None:
        raw = make_raw_request()
        raw["currentStatus"] = {}
        req = to_jsm_request(raw)
        assert req.status == "UNKNOWN"

    def test_resolution_beats_status_date_for_updated_at(self) -> None:
        raw = make_raw_request(
            created_iso="2026-05-06T10:00:00.000+0000",
            status_date_iso="2026-05-06T11:00:00.000+0000",
            resolution_iso="2026-05-06T12:00:00.000+0000",
        )
        req = to_jsm_request(raw)
        assert req.updated_at == datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
        assert req.resolved_at == datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


class TestToJsmCustomer:
    def test_none(self) -> None:
        assert to_jsm_customer(None) is None

    def test_partial_fields(self) -> None:
        customer = to_jsm_customer({"displayName": "Ghost"})
        assert customer is not None
        assert customer.display_name == "Ghost"
        assert customer.email is None
