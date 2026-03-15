from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from jira import JIRA

from onyx.connectors.jira_service_management import utils as jsm_utils
from onyx.connectors.jira_service_management.utils import append_with_byte_limit
from onyx.connectors.jira_service_management.utils import build_queue_membership_map
from onyx.connectors.jira_service_management.utils import format_approval_summaries
from onyx.connectors.jira_service_management.utils import get_customer_request
from onyx.connectors.jira_service_management.utils import iter_jsm_paginated_values
from onyx.connectors.jira_service_management.utils import list_request_approvals
from onyx.connectors.jira_service_management.utils import list_request_slas
from onyx.connectors.jira_service_management.utils import JSMQueue


def _make_http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response._content = b"{}"
    response.url = "https://jira.example.com/rest/servicedeskapi/request/HELP-1"
    return requests.HTTPError(response=response)


def test_get_customer_request_treats_403_as_permission_boundary() -> None:
    jira_client = MagicMock(spec=JIRA)

    with patch(
        "onyx.connectors.jira_service_management.utils.jsm_get_json",
        side_effect=_make_http_error(403),
    ):
        request = get_customer_request(
            jira_client=jira_client,
            issue_id_or_key="HELP-1",
        )

    assert request is None


def test_build_queue_membership_map_keeps_known_issues_after_limit() -> None:
    jira_client = MagicMock(spec=JIRA)
    triage_queue = JSMQueue(
        queue_id="1",
        name="Triage",
        jql="project = HELP",
        issue_count=1,
    )
    urgent_queue = JSMQueue(
        queue_id="2",
        name="Urgent",
        jql="project = HELP",
        issue_count=2,
    )

    def _iter_values(*, path: str, **_: object):
        if path.endswith("/queue/1/issue"):
            return iter([{"issueKey": "HELP-1"}])
        if path.endswith("/queue/2/issue"):
            return iter(
                [
                    {"issueKey": "HELP-1"},
                    {"issueKey": "HELP-2"},
                ]
            )
        raise AssertionError(f"Unexpected path {path}")

    with (
        patch(
            "onyx.connectors.jira_service_management.utils.list_queues",
            return_value=[triage_queue, urgent_queue],
        ),
        patch(
            "onyx.connectors.jira_service_management.utils.iter_jsm_paginated_values",
            side_effect=_iter_values,
        ),
    ):
        membership = build_queue_membership_map(
            jira_client=jira_client,
            service_desk_id="1",
            queue_scan_limit=1,
        )

    assert membership == {
        "HELP-1": [triage_queue, urgent_queue],
    }
    assert "HELP-2" not in membership


@pytest.mark.parametrize("max_bytes", [0, 1, 2, 3])
def test_append_with_byte_limit_respects_tiny_byte_limits(max_bytes: int) -> None:
    result = append_with_byte_limit(
        existing_text="",
        text_to_append="abcdef",
        max_bytes=max_bytes,
    )

    assert len(result.encode("utf-8")) <= max_bytes


def test_iter_jsm_paginated_values_stops_after_page_limit() -> None:
    jira_client = MagicMock(spec=JIRA)

    with (
        patch.object(jsm_utils, "JSM_MAX_PAGINATION_PAGES", 2),
        patch(
            "onyx.connectors.jira_service_management.utils.jsm_get_json",
            return_value={"values": [{"id": "1"}], "size": 1},
        ) as mock_get_json,
        patch("onyx.connectors.jira_service_management.utils.logger.warning") as mock_warn,
    ):
        values = list(
            iter_jsm_paginated_values(
                jira_client=jira_client,
                path="servicedesk/1/queue",
            )
        )

    assert values == [{"id": "1"}, {"id": "1"}]
    assert mock_get_json.call_count == 2
    mock_warn.assert_called_once()


def test_list_request_slas_uses_optional_pagination() -> None:
    jira_client = MagicMock(spec=JIRA)

    with patch(
        "onyx.connectors.jira_service_management.utils.iter_jsm_paginated_values_optional",
        return_value=iter([{"name": "Time to first response"}, {"name": "Time to resolution"}]),
    ) as mock_iter:
        slas = list_request_slas(jira_client=jira_client, issue_id_or_key="HELP-1")

    assert slas == [{"name": "Time to first response"}, {"name": "Time to resolution"}]
    mock_iter.assert_called_once()


def test_list_request_approvals_uses_optional_pagination() -> None:
    jira_client = MagicMock(spec=JIRA)

    with patch(
        "onyx.connectors.jira_service_management.utils.iter_jsm_paginated_values_optional",
        return_value=iter([{"id": "1"}, {"id": "2"}]),
    ) as mock_iter:
        approvals = list_request_approvals(
            jira_client=jira_client,
            issue_id_or_key="HELP-1",
        )

    assert approvals == [{"id": "1"}, {"id": "2"}]
    mock_iter.assert_called_once()


def test_format_approval_summaries_ignores_can_answer_approval_boolean() -> None:
    summaries = format_approval_summaries(
        [
            {
                "name": "Manager approval",
                "canAnswerApproval": True,
                "approvers": [
                    {
                        "approver": {
                            "displayName": "Dana Manager",
                            "emailAddress": "dana@example.com",
                        }
                    }
                ],
            }
        ]
    )

    assert summaries == ["Manager approval: pending (Dana Manager)"]
