"""Unit tests for JiraServiceManagementConnector.

Covers the failure modes called out in review of prior attempts at
https://github.com/onyx-dot-app/onyx/issues/2281: pagination cursor drift,
incremental-poll window filtering, credential validation, and error mapping.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    make_page,
    make_raw_request,
)


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


def _docs_from_batches(batches) -> list[Document]:
    return [doc for batch in batches for doc in batch]


def _ts(year, month, day, hour, minute=0) -> int:
    return int(
        datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()
    )


class TestLoadFromState:
    def test_single_page(self, connector, mock_jsm_session) -> None:
        page = make_page([make_raw_request()], is_last_page=True)
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(json_data=page)
            batches = list(connector.load_from_state())

        docs = _docs_from_batches(batches)
        assert len(docs) == 1
        doc = docs[0]
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.semantic_identifier == "IT-1 Printer on fire"
        assert doc.id == "https://acme.atlassian.net/servicedesk/customer/portal/1/IT-1"
        assert doc.metadata["request_type"] == "Get IT help"
        assert doc.metadata["status"] == "In Progress"
        assert doc.metadata["service_desk_id"] == "1"
        # primary owner is the reporter
        assert doc.primary_owners and doc.primary_owners[0].display_name == "Alice"
        # created 10:00, statusDate 11:00 -> updated_at is the later
        assert doc.doc_updated_at is not None
        assert doc.doc_updated_at.hour == 11
        assert doc.doc_updated_at.tzinfo == timezone.utc

    def test_pagination_across_pages_and_short_page(
        self, connector, mock_jsm_session
    ) -> None:
        """Cursor must advance by len(values), not page_size, so a short page
        cannot desync pagination (drift bug from prior PR review)."""
        page1 = make_page(
            [make_raw_request(issue_key="IT-1"), make_raw_request(issue_key="IT-2")],
            is_last_page=False,
        )
        # short page: server returned fewer than `limit`
        page2 = make_page([make_raw_request(issue_key="IT-3")], is_last_page=True)
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.side_effect = [
                _mock_response(json_data=page1),
                _mock_response(json_data=page2),
            ]
            docs = _docs_from_batches(connector.load_from_state())

        assert [d.semantic_identifier.split()[0] for d in docs] == [
            "IT-1",
            "IT-2",
            "IT-3",
        ]
        # second call must use start=2 (len of first page), not start=page_size
        second_call_kwargs = mock_jsm_session.get.call_args_list[1].kwargs
        assert second_call_kwargs["params"]["start"] == 2

    def test_empty_page_stops(self, connector, mock_jsm_session) -> None:
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(
                json_data=make_page([], is_last_page=False)
            )
            docs = _docs_from_batches(connector.load_from_state())
        assert docs == []

    def test_request_status_filter_forwarded(
        self,
        jsm_domain,
        service_desk_id,
        user_email,
        api_token,
        mock_jsm_session,
    ) -> None:
        connector = JiraServiceManagementConnector(
            jsm_domain=jsm_domain,
            service_desk_id=service_desk_id,
            request_status="OPEN",
        )
        connector.load_credentials(
            {"jira_user_email": user_email, "jira_api_token": api_token}
        )
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(
                json_data=make_page([], is_last_page=False)
            )
            list(connector.load_from_state())
        sent_params = mock_jsm_session.get.call_args.kwargs["params"]
        assert sent_params["requestStatus"] == "OPEN"
        assert sent_params["serviceDeskId"] == "1"


class TestPollSource:
    def test_window_filters_out_old_requests(self, connector, mock_jsm_session) -> None:
        # created 2026-05-06T10:00 UTC, statusDate 11:00 -> updated 11:00
        page = make_page([make_raw_request()], is_last_page=True)
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(json_data=page)
            # window 12:00->13:00 excludes the 11:00 update
            docs = _docs_from_batches(
                connector.poll_source(_ts(2026, 5, 6, 12), _ts(2026, 5, 6, 13))
            )
        assert docs == []

    def test_window_includes_recent_requests(self, connector, mock_jsm_session) -> None:
        page = make_page([make_raw_request()], is_last_page=True)
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(json_data=page)
            # window 10:30->12:00 includes the 11:00 update
            docs = _docs_from_batches(
                connector.poll_source(_ts(2026, 5, 6, 10, 30), _ts(2026, 5, 6, 12))
            )
        assert len(docs) == 1


class TestCredentialsAndValidation:
    def test_missing_required_args(self) -> None:
        with pytest.raises(ConnectorValidationError):
            JiraServiceManagementConnector(jsm_domain="", service_desk_id="1")
        with pytest.raises(ConnectorValidationError):
            JiraServiceManagementConnector(
                jsm_domain="acme.atlassian.net", service_desk_id=""
            )

    def test_load_credentials_missing_keys(self, jsm_domain, service_desk_id) -> None:
        connector = JiraServiceManagementConnector(
            jsm_domain=jsm_domain, service_desk_id=service_desk_id
        )
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials({"jira_user_email": "x@example.com"})

    def test_validate_ok(self, connector, mock_jsm_session) -> None:
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(
                json_data={"serviceDeskId": 1, "projectName": "IT"}
            )
            connector.validate_connector_settings()  # should not raise
        called_path = mock_jsm_session.get.call_args.args[0]
        assert called_path.endswith("/rest/servicedeskapi/servicedesk/1")

    @pytest.mark.parametrize(
        "status_code,expected_exc",
        [
            (401, CredentialExpiredError),
            (403, InsufficientPermissionsError),
            (404, ConnectorValidationError),
        ],
    )
    def test_validate_error_mapping(
        self,
        connector,
        mock_jsm_session,
        status_code: int,
        expected_exc: type[Exception],
    ) -> None:
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(
                status_code=status_code, json_data={}
            )
            with pytest.raises(expected_exc):
                connector.validate_connector_settings()


class TestHardening:
    """Defensive behaviours validated during the adversarial review of this
    connector: input rejection at the constructor, pagination-loop guards,
    per-item fault tolerance, and poll-window sanitisation."""

    @pytest.mark.parametrize(
        "bad_id", ["../..", "../../rest/api/3/search", "1 OR 1=1", "", " ", None]
    )
    def test_service_desk_id_rejected(self, bad_id) -> None:
        with pytest.raises(ConnectorValidationError):
            JiraServiceManagementConnector(
                jsm_domain="acme.atlassian.net", service_desk_id=bad_id
            )

    def test_page_size_string_coerced(self, jsm_domain, service_desk_id) -> None:
        connector = JiraServiceManagementConnector(
            jsm_domain=jsm_domain, service_desk_id=service_desk_id, page_size="50"
        )
        assert connector._page_size == 50

    @pytest.mark.parametrize(
        "bad_credentials",
        [
            {"jira_user_email": None, "jira_api_token": "tok"},
            {"jira_user_email": "a@b.c", "jira_api_token": 12345},
            {"jira_user_email": "a@b.c", "jira_api_token": ""},
        ],
    )
    def test_bad_credentials_rejected(
        self, jsm_domain, service_desk_id, bad_credentials
    ) -> None:
        connector = JiraServiceManagementConnector(
            jsm_domain=jsm_domain, service_desk_id=service_desk_id
        )
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials(bad_credentials)

    def test_server_replaying_first_page_stops(
        self, connector, mock_jsm_session
    ) -> None:
        """A server (or proxy) that ignores `start` and keeps replaying the
        same non-empty page must not loop forever."""
        page = make_page([make_raw_request()], is_last_page=False)
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(json_data=page)
            docs = _docs_from_batches(connector.load_from_state())

        assert len(docs) == 1
        # first page + the all-duplicate page that trips the guard
        assert mock_jsm_session.get.call_count == 2

    def test_single_malformed_item_skipped(self, connector, mock_jsm_session) -> None:
        """One unparseable ticket must not kill the whole sync; the rest of
        the page still indexes."""
        bad = make_raw_request(issue_key="BAD-1")
        bad["createdDate"] = "garbage-str"
        page = make_page([bad, make_raw_request(issue_key="GOOD-1")], is_last_page=True)
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(json_data=page)
            docs = _docs_from_batches(connector.load_from_state())

        assert [d.semantic_identifier.split()[0] for d in docs] == ["GOOD-1"]

    @pytest.mark.parametrize(
        "start,end",
        [
            (-86400, 0),  # negative
            (float("nan"), 100),  # NaN
            (0, float("inf")),  # infinity
            (0, 1e20),  # out-of-range
        ],
    )
    def test_poll_source_survives_degenerate_timestamps(
        self, connector, mock_jsm_session, start, end
    ) -> None:
        with patch(
            "onyx.connectors.jira_service_management.connector.build_jsm_session",
            return_value=mock_jsm_session,
        ):
            mock_jsm_session.get.return_value = _mock_response(
                json_data=make_page([], is_last_page=True)
            )
            # must not raise OSError/OverflowError/ValueError
            list(connector.poll_source(start, end))
