"""Unit tests for the Jira Service Management (JSM) connector."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from onyx.connectors.jira.service_management import (
    JiraServiceManagementConnector,
    JsmCustomerRequest,
    jsm_request_to_document,
    parse_iso_timestamp,
    parse_jsm_approvals,
    parse_jsm_sla_values,
)


def test_parse_iso_timestamp_handles_utc_and_offset() -> None:
    assert parse_iso_timestamp("2026-05-01T12:00:00Z") == 1777636800
    assert parse_iso_timestamp("2026-05-01T12:00:00+0000") == 1777636800
    assert parse_iso_timestamp(None) == 0


def test_parse_jsm_sla_and_approvals() -> None:
    sla_payload = {
        "values": [
            {
                "name": "Time to first response",
                "ongoingCycle": {
                    "elapsedTime": {"millis": 950000},
                    "goalDuration": {"millis": 900000},
                    "breached": True,
                    "paused": False,
                },
            }
        ]
    }
    slas = parse_jsm_sla_values(sla_payload)
    assert len(slas) == 1
    assert slas[0].name == "Time to first response"
    assert slas[0].breached is True
    assert slas[0].elapsed_millis == 950000

    approval_payload = {
        "values": [
            {
                "id": "10",
                "name": "CAB Change Approval",
                "finalDecision": "approved",
                "approvers": [
                    {"approver": {"emailAddress": "secops@example.com"}}
                ],
            }
        ]
    }
    approvals = parse_jsm_approvals(approval_payload)
    assert len(approvals) == 1
    assert approvals[0].final_decision == "approved"
    assert approvals[0].approvers == ["secops@example.com"]


def test_jsm_connector_polls_service_desk_requests_and_builds_documents() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net",
        service_desk_id="4",
        include_sla=True,
        include_approvals=True,
    )
    connector.load_credentials({"jira_user_email": "bot@acme.io", "jira_api_token": "tok"})

    def fake_get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/rest/servicedeskapi/request":
            return {
                "isLastPage": True,
                "values": [
                    {
                        "issueId": "10042",
                        "issueKey": "ITSD-42",
                        "serviceDeskId": "4",
                        "requestTypeId": "19",
                        "requestFieldValues": [
                            {"fieldId": "summary", "value": "Production VPN Gateway Outage"},
                            {"fieldId": "description", "value": "Users in EU region cannot authenticate."},
                            {"fieldId": "organizations", "value": [{"id": "1", "name": "Enterprise EMEA"}]},
                        ],
                        "currentStatus": {
                            "status": "Escalated",
                            "statusDate": {"iso8601": "2026-05-01T13:00:00Z"},
                        },
                        "createdDate": {"iso8601": "2026-05-01T12:00:00Z"},
                        "reporter": {"emailAddress": "alice@acme.io", "displayName": "Alice"},
                        "_links": {"web": "https://acme.atlassian.net/servicedesk/customer/portal/4/ITSD-42"},
                    }
                ],
            }
        if path.endswith("/sla"):
            return {
                "values": [
                    {
                        "name": "Time to resolution",
                        "ongoingCycle": {
                            "elapsedTime": {"millis": 3600000},
                            "goalDuration": {"millis": 1800000},
                            "breached": True,
                        },
                    }
                ]
            }
        if path.endswith("/approval"):
            return {
                "values": [
                    {
                        "id": "1",
                        "name": "Emergency Change Approval",
                        "finalDecision": "approved",
                        "approvers": [{"approver": {"emailAddress": "cto@acme.io"}}],
                    }
                ]
            }
        if path.endswith("/comment"):
            return {"values": [{"body": "Failover tunnel activated."}]}
        return {"values": []}

    connector._get_json = MagicMock(side_effect=fake_get_json)  # type: ignore[method-assign]

    batches = list(connector.poll_source(start=0))
    assert len(batches) == 1
    docs = batches[0]
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == "https://acme.atlassian.net/servicedesk/customer/portal/4/ITSD-42"
    assert doc.metadata["issue_key"] == "ITSD-42"
    assert doc.metadata["sla_breached"] == "true"
    assert doc.metadata["organizations"] == ["Enterprise EMEA"]
    assert len(doc.sections) == 2
    assert "Time to resolution: BREACHED" in doc.sections[0].text
    assert "Failover tunnel activated." in doc.sections[1].text
