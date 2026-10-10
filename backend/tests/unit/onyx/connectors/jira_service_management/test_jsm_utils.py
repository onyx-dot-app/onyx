from unittest.mock import MagicMock

from jira import JIRA
from jira.resources import Issue

from onyx.connectors.jira_service_management.utils import (
    CUSTOMER_REQUEST_TYPE_FIELD_NAME,
    ORGANIZATIONS_FIELD_NAME,
    discover_jsm_fields,
    extract_customer_request_type,
    extract_organizations,
    extract_sla_info,
    get_jsm_comment_strs,
)
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    MockComment,
    MockUser,
    make_mock_jsm_issue,
)


class TestDiscoverJsmFields:
    def test_discovers_fields_by_display_name(self) -> None:
        client = MagicMock(spec=JIRA)
        client.fields.return_value = [
            {"id": "customfield_10003", "name": "Team"},
            {
                "id": "customfield_10010",
                "name": CUSTOMER_REQUEST_TYPE_FIELD_NAME,
            },
            {"id": "customfield_10001", "name": ORGANIZATIONS_FIELD_NAME},
        ]

        field_map = discover_jsm_fields(client)
        assert field_map.customer_request_type == "customfield_10010"
        assert field_map.organizations == "customfield_10001"

    def test_returns_empty_map_when_fields_unavailable(self) -> None:
        client = MagicMock(spec=JIRA)
        client.fields.side_effect = RuntimeError("not permitted")

        field_map = discover_jsm_fields(client)
        assert field_map.customer_request_type is None
        assert field_map.organizations is None


class TestExtractCustomerRequestType:
    def test_by_field_id_string_value(self) -> None:
        # Cloud returns "<serviceDeskId>/<requestTypeId>" strings
        issue = make_mock_jsm_issue(request_type="helpdesk/12")
        assert (
            extract_customer_request_type(issue, "customfield_10010") == "helpdesk/12"
        )

    def test_by_field_id_object_value(self) -> None:
        issue = make_mock_jsm_issue(
            request_type=None,
            raw_overrides={
                "customfield_10010": {"requestType": {"name": "Get IT help"}}
            },
        )
        assert (
            extract_customer_request_type(issue, "customfield_10010") == "Get IT help"
        )

    def test_structural_fallback_without_field_id(self) -> None:
        issue = make_mock_jsm_issue(
            request_type=None,
            raw_overrides={
                "customfield_12345": {"name": "Wifi access", "serviceDeskId": "7"}
            },
        )
        assert extract_customer_request_type(issue) == "Wifi access"

    def test_missing_everywhere_returns_none(self) -> None:
        issue = make_mock_jsm_issue(request_type=None)
        assert extract_customer_request_type(issue, "customfield_10010") is None


class TestExtractOrganizations:
    def test_by_field_id(self) -> None:
        issue = make_mock_jsm_issue(organizations=["Acme", "Beta LLC"])
        assert extract_organizations(issue, "customfield_10001") == [
            "Acme",
            "Beta LLC",
        ]

    def test_structural_fallback(self) -> None:
        issue = make_mock_jsm_issue(
            organizations=None,
            raw_overrides={"customfield_55555": [{"id": "3", "name": "Initech"}]},
        )
        assert extract_organizations(issue) == ["Initech"]

    def test_no_organizations_returns_empty_list(self) -> None:
        issue = make_mock_jsm_issue(organizations=[])
        assert extract_organizations(issue, "customfield_10001") == []


class TestExtractSlaInfo:
    def test_ongoing_and_completed_cycles(self) -> None:
        issue = make_mock_jsm_issue(
            slas={
                "customfield_10020": {
                    "name": "Time to first response",
                    "ongoingCycle": {"breached": False},
                },
                "customfield_10021": {
                    "name": "Time to resolution",
                    "completedCycles": [{"breached": True}],
                },
            }
        )
        assert extract_sla_info(issue) == {
            "Time to first response": "In Progress",
            "Time to resolution": "Breached",
        }

    def test_no_sla_fields_returns_empty_dict(self) -> None:
        issue = make_mock_jsm_issue()
        assert extract_sla_info(issue) == {}


class TestGetJsmCommentStrs:
    def test_public_comments_only_by_default(self) -> None:
        issue = make_mock_jsm_issue()
        comments = get_jsm_comment_strs(issue)
        assert comments == ["Have you tried restarting your laptop?"]

    def test_internal_comments_included_and_tagged(self) -> None:
        issue = make_mock_jsm_issue()
        comments = get_jsm_comment_strs(issue, include_internal_comments=True)
        assert comments == [
            "Have you tried restarting your laptop?",
            "[Internal Note] Checked the VPN gateway logs; cert expired.",
        ]

    def test_blacklisted_author_skipped(self) -> None:
        issue = make_mock_jsm_issue(
            comments=[
                MockComment(
                    body="from bob",
                    author=MockUser("Bob Agent", "bob@example.com"),
                ),
                MockComment(
                    body="from alice",
                    author=MockUser("Alice", "alice@example.com"),
                ),
            ]
        )
        comments = get_jsm_comment_strs(
            issue, comment_email_blacklist=("bob@example.com",)
        )
        assert comments == ["from alice"]

    def test_no_comments_attribute(self) -> None:
        issue = MagicMock(spec=Issue)  # spec'd mock: no fields materialized
        assert get_jsm_comment_strs(issue) == []
