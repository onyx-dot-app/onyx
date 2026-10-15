"""Tests for JiraConnector.reindex against the live Jira Cloud test site.

Project AS holds two issues: the Story AS-3 and its parent Epic AS-4.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JIRA_API_TOKEN_SCOPED,
)

_SITE = "https://danswerai.atlassian.net"
_PROJECT = "AS"
_STORY_ID = f"{_SITE}/browse/AS-3"
_EPIC_ID = f"{_SITE}/browse/AS-4"


def _make_connector(
    test_secrets: dict[TestSecret, str],
    scoped_token: bool = False,
    jql_query: str | None = None,
) -> JiraConnector:
    connector = JiraConnector(
        jira_base_url=_SITE,
        project_key=None if jql_query else _PROJECT,
        jql_query=jql_query,
        comment_email_blacklist=[],
        scoped_token=scoped_token,
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": (
                test_secrets[TestSecret.JIRA_API_TOKEN_SCOPED]
                if scoped_token
                else test_secrets[TestSecret.JIRA_API_TOKEN]
            ).strip(),
        }
    )
    return connector


@pytest.fixture
def jira_connector(test_secrets: dict[TestSecret, str]) -> JiraConnector:
    return _make_connector(test_secrets)


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id, document_link=doc_id),
            failure_message=f"Synthetic failure for {doc_id}",
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure], list[HierarchyNode]]:
    return (
        [r for r in results if isinstance(r, Document)],
        [r for r in results if isinstance(r, ConnectorFailure)],
        [r for r in results if isinstance(r, HierarchyNode)],
    )


def _failed_doc_ids(failures: list[ConnectorFailure]) -> list[str]:
    return [
        f.failed_document.document_id for f in failures if f.failed_document is not None
    ]


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_matches_crawl(
    mock_api_key: MagicMock,  # noqa: ARG001
    jira_connector: JiraConnector,
) -> None:
    crawled = {
        doc.id: doc
        for doc in load_all_from_connector(jira_connector, 0, time.time()).documents
    }
    assert set(crawled) == {_STORY_ID, _EPIC_ID}

    docs, failures, nodes = _split(
        list(jira_connector.reindex(_build_failures([_STORY_ID])))
    )

    assert failures == []
    assert [d.id for d in docs] == [_STORY_ID]
    assert docs[0].semantic_identifier == crawled[_STORY_ID].semantic_identifier
    assert docs[0].sections == crawled[_STORY_ID].sections
    assert (
        docs[0].parent_hierarchy_raw_node_id
        == crawled[_STORY_ID].parent_hierarchy_raw_node_id
    )
    # The project and the parent Epic, parents before the document.
    assert [n.raw_node_id for n in nodes] == [_PROJECT, "AS-4"]
    assert docs[0].external_access is None


@pytest.mark.parametrize("scoped_token", [False, True])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_multiple_issues(
    mock_api_key: MagicMock,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
    scoped_token: bool,
) -> None:
    connector = _make_connector(test_secrets, scoped_token=scoped_token)
    # Duplicate ids are fetched once.
    docs, failures, nodes = _split(
        list(connector.reindex(_build_failures([_STORY_ID, _EPIC_ID, _STORY_ID])))
    )

    assert failures == []
    assert sorted(d.id for d in docs) == [_STORY_ID, _EPIC_ID]
    assert sorted(n.raw_node_id for n in nodes) == [_PROJECT, "AS-4"]


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_missing_issue_yields_failure(
    mock_api_key: MagicMock,  # noqa: ARG001
    jira_connector: JiraConnector,
) -> None:
    bogus = f"{_SITE}/browse/AS-999999"

    docs, failures, _ = _split(
        list(jira_connector.reindex(_build_failures([bogus, _STORY_ID])))
    )

    assert [d.id for d in docs] == [_STORY_ID]
    assert _failed_doc_ids(failures) == [bogus]


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_out_of_scope_issue_yields_failure(
    mock_api_key: MagicMock,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    connector = _make_connector(
        test_secrets, jql_query=f"project = '{_PROJECT}' AND issuetype = Story"
    )

    docs, failures, _ = _split(
        list(connector.reindex(_build_failures([_STORY_ID, _EPIC_ID])))
    )

    assert [d.id for d in docs] == [_STORY_ID]
    assert _failed_doc_ids(failures) == [_EPIC_ID]


def test_reindex_unparseable_ids_yield_failures(
    jira_connector: JiraConnector,
) -> None:
    weird = [
        f"{_SITE}/projects/{_PROJECT}",
        f"{_SITE}/browse/not-a-key",
        "https://other.atlassian.net/browse/AS-3",
    ]

    docs, failures, nodes = _split(list(jira_connector.reindex(_build_failures(weird))))

    assert docs == []
    assert nodes == []
    assert _failed_doc_ids(failures) == weird


def test_reindex_empty_errors(jira_connector: JiraConnector) -> None:
    assert list(jira_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(jira_connector: JiraConnector) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="some_stage"),
        failure_message="retrieval failure",
    )

    assert list(jira_connector.reindex([entity])) == []


@pytest.mark.usefixtures("enable_ee")
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_with_permissions(
    mock_api_key: MagicMock,  # noqa: ARG001
    jira_connector: JiraConnector,
) -> None:
    docs, failures, _ = _split(
        list(
            jira_connector.reindex(
                _build_failures([_STORY_ID, _EPIC_ID]), include_permissions=True
            )
        )
    )

    assert failures == []
    assert sorted(d.id for d in docs) == [_STORY_ID, _EPIC_ID]
    for doc in docs:
        assert doc.external_access is not None
        assert (
            doc.external_access.is_public
            or doc.external_access.external_user_emails
            or doc.external_access.external_user_group_ids
        )
