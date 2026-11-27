"""Jira Service Management indexing without a live site.

The service desk list is the full set. A poll uses Jira search. Internal
comments follow the connector flag. Slim ids match the indexed ids.
"""

from typing import Any
from unittest.mock import MagicMock

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementCheckpoint,
    JiraServiceManagementConnector,
    project_jql,
)
from onyx.connectors.jira_service_management.models import (
    CommentPage,
    CustomerRequest,
    IssueRef,
    IssueSearchPage,
    RequestPage,
    ServiceDesk,
)
from onyx.connectors.models import Document, HierarchyNode, SlimDocument

_BASE = "https://example.atlassian.net"
_DESK = ServiceDesk.model_validate(
    {
        "id": "10",
        "projectId": "100",
        "projectKey": "IT",
        "projectName": "IT Help",
    }
)


def _request(issue_id: str, key: str, **overrides: Any) -> CustomerRequest:
    raw: dict[str, Any] = {
        "issueId": issue_id,
        "issueKey": key,
        "createdDate": {"epochMillis": 1_700_000_000_000},
        "reporter": {"displayName": "Ada", "emailAddress": "ada@example.com"},
        "requestType": {"id": "25", "name": "Get IT help"},
        "currentStatus": {
            "status": "Waiting for support",
            "statusDate": {"epochMillis": 1_700_000_100_000},
        },
        "requestFieldValues": [
            {"fieldId": "summary", "value": "VPN is down"},
            {
                "fieldId": "description",
                "value": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Since Monday"}],
                        }
                    ],
                },
            },
        ],
    }
    raw.update(overrides)
    return CustomerRequest.model_validate(raw)


def _comments(*bodies: tuple[str, bool]) -> CommentPage:
    return CommentPage.model_validate(
        {
            "isLastPage": True,
            "values": [
                {
                    "id": str(index),
                    "body": body,
                    "public": public,
                    "created": {"epochMillis": 1_700_000_200_000 + index},
                }
                for index, (body, public) in enumerate(bodies, start=1)
            ],
        }
    )


def _connector(**kwargs: Any) -> tuple[JiraServiceManagementConnector, MagicMock]:
    connector = JiraServiceManagementConnector(
        jira_base_url=f"{_BASE}/",
        project_key="it",
        **kwargs,
    )
    ops = MagicMock()
    ops.find_service_desk.return_value = _DESK
    ops.list_comments.return_value = _comments(
        ("public note", True), ("agent note", False)
    )
    connector._ops = ops
    return connector, ops


def _run(
    connector: JiraServiceManagementConnector,
    start: float = 0,
    end: float = 1_800_000_000,
) -> tuple[list[Document | HierarchyNode], JiraServiceManagementCheckpoint]:
    items: list[Document | HierarchyNode] = []
    checkpoint = connector.build_dummy_checkpoint()
    wrapper = CheckpointOutputWrapper[JiraServiceManagementCheckpoint]()
    while True:
        finished = False
        for document, node, failure, nxt in wrapper(
            connector.load_from_checkpoint(start, end, checkpoint)
        ):
            assert failure is None
            if document is not None:
                items.append(document)
            if node is not None:
                items.append(node)
            if nxt is not None:
                checkpoint = nxt
                finished = True
        if not checkpoint.has_more:
            break
        if not finished:
            break
    return items, checkpoint


def test_project_jql_uses_epoch_milliseconds() -> None:
    assert project_jql("IT") == 'project = "IT"'
    assert (
        project_jql("IT", 1_700_000_000.5, 1_700_000_100)
        == 'project = "IT" AND updated >= 1700000000500 AND updated <= 1700000100000'
    )


def test_full_run_indexes_request_text_and_both_comments() -> None:
    connector, ops = _connector()
    ops.list_requests.return_value = RequestPage.model_validate(
        {
            "isLastPage": True,
            "values": [_request("100", "IT-1").model_dump(by_alias=True)],
        }
    )

    items, checkpoint = _run(connector)

    documents = [item for item in items if isinstance(item, Document)]
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert checkpoint.has_more is False
    assert len(nodes) == 1
    assert nodes[0].display_name == "IT Help"
    assert len(documents) == 1
    document = documents[0]
    assert document.id == f"{_BASE}/servicedesk/request/100"
    assert document.semantic_identifier == "[IT-1] VPN is down"
    assert document.metadata["request_type"] == "Get IT help"
    assert document.metadata["status"] == "Waiting for support"
    texts = [section.text for section in document.sections]
    assert texts == ["Since Monday", "public note", "agent note"]
    assert document.primary_owners is not None
    assert document.primary_owners[0].email == "ada@example.com"
    ops.search_issues.assert_not_called()


def test_internal_comments_can_be_left_out() -> None:
    connector, ops = _connector(include_internal_comments=False)
    ops.list_requests.return_value = RequestPage(
        values=[_request("100", "IT-1")], is_last_page=True
    )

    items, _checkpoint = _run(connector)

    document = next(item for item in items if isinstance(item, Document))
    texts = [section.text for section in document.sections]
    assert texts == ["Since Monday", "public note"]


def test_poll_uses_search_and_skips_issues_that_are_not_requests() -> None:
    connector, ops = _connector()
    ops.search_issues.return_value = IssueSearchPage(
        issues=[IssueRef(key="IT-1"), IssueRef(key="IT-2")],
        is_last=True,
        uses_token=True,
    )
    ops.get_request.side_effect = lambda *, issue_key: (
        _request("100", "IT-1") if issue_key == "IT-1" else None
    )

    items, checkpoint = _run(connector, start=1_700_000_000, end=1_700_000_100)

    documents = [item for item in items if isinstance(item, Document)]
    assert [document.id for document in documents] == [
        f"{_BASE}/servicedesk/request/100"
    ]
    assert checkpoint.has_more is False
    jql = ops.search_issues.call_args.kwargs["jql"]
    assert "updated >= 1700000000000" in jql
    assert "updated <= 1700000100000" in jql
    ops.list_requests.assert_not_called()


def test_a_second_page_resumes_after_the_overlap() -> None:
    connector, ops = _connector()
    first = [_request(str(1000 + index), f"IT-{index}") for index in range(1, 51)]
    second = [_request("2000", "IT-51")]
    ops.list_requests.side_effect = [
        RequestPage(values=first, is_last_page=False),
        RequestPage(values=second, is_last_page=True),
    ]

    items, checkpoint = _run(connector)

    documents = [item for item in items if isinstance(item, Document)]
    assert len(documents) == 51
    assert checkpoint.has_more is False
    assert ops.list_requests.call_args_list[1].kwargs["start"] == 45


def test_slim_ids_match_a_full_index() -> None:
    connector, ops = _connector()
    request = _request("100", "IT-1")
    ops.list_requests.return_value = RequestPage(values=[request], is_last_page=True)

    items, _checkpoint = _run(connector)
    indexed = [item.id for item in items if isinstance(item, Document)]
    slim = [
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    assert slim == indexed == [f"{_BASE}/servicedesk/request/100"]
