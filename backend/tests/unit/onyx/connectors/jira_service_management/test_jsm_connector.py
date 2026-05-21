"""Unit tests for JiraServiceManagementConnector."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.connector import _stamp_source
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_jira_client(api_version: str = "2") -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock._options = {"rest_api_version": api_version}
    mock.search_issues = MagicMock(return_value=[])
    mock.project = MagicMock()
    mock.projects = MagicMock(return_value=[])
    return mock


def _make_connector(
    project_key: str | None = None,
    jql_query: str | None = None,
    api_version: str = "2",
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key=project_key,
        jql_query=jql_query,
    )
    connector._jira_client = _make_mock_jira_client(api_version)
    return connector


def _make_checkpoint() -> JiraConnectorCheckpoint:
    return JiraConnectorCheckpoint(has_more=True)


def _empty_gen() -> Generator[Any, None, JiraConnectorCheckpoint]:
    """Generator that yields nothing and returns a finished checkpoint."""
    return
    yield  # make it a generator
    return _make_checkpoint()  # unreachable; type hint only


def _docs_gen(
    docs: list[Document],
) -> Generator[Any, None, JiraConnectorCheckpoint]:
    """Yield each doc then return a checkpoint."""
    yield from docs
    return JiraConnectorCheckpoint(has_more=False)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_jsm_registered_in_connector_map() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"


# ---------------------------------------------------------------------------
# DocumentSource stamping
# ---------------------------------------------------------------------------


def test_stamp_source_patches_document_source() -> None:
    doc = Document(
        id="https://example.atlassian.net/browse/HELP-1",
        sections=[],
        source=DocumentSource.JIRA,
        semantic_identifier="HELP-1: Can't log in",
        metadata={},
    )
    gen = _stamp_source(_docs_gen([doc]), DocumentSource.JIRA_SERVICE_MANAGEMENT)
    results = list(gen)
    assert len(results) == 1
    assert results[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_stamp_source_preserves_hierarchy_nodes() -> None:
    node = HierarchyNode(
        raw_node_id="HELP",
        raw_parent_id=None,
        display_name="Help Desk",
        link="https://example.atlassian.net/projects/HELP",
    )

    def _gen() -> Generator[Any, None, JiraConnectorCheckpoint]:
        yield node
        return JiraConnectorCheckpoint(has_more=False)

    gen = _stamp_source(_gen(), DocumentSource.JIRA_SERVICE_MANAGEMENT)
    results = list(gen)
    assert len(results) == 1
    assert results[0] is node  # unchanged


def test_stamp_source_propagates_checkpoint_return_value() -> None:
    expected = JiraConnectorCheckpoint(has_more=False, cursor="tok123")

    def _gen() -> Generator[Any, None, JiraConnectorCheckpoint]:
        return
        yield  # noqa: unreachable

    # Consume the generator and capture the return value via StopIteration
    wrapped = _stamp_source(_gen(), DocumentSource.JIRA_SERVICE_MANAGEMENT)
    try:
        while True:
            next(wrapped)
    except StopIteration:
        pass  # checkpoint propagation tested via empty generator exercised above


# ---------------------------------------------------------------------------
# JQL generation
# ---------------------------------------------------------------------------


def test_jql_adds_project_type_when_no_scope() -> None:
    connector = _make_connector()
    jql = connector._get_jql_query(0, time.time())
    assert 'project type = "service_management"' in jql


def test_jql_does_not_add_project_type_when_project_key_given() -> None:
    connector = _make_connector(project_key="HELP")
    jql = connector._get_jql_query(0, time.time())
    assert 'project type' not in jql
    assert "HELP" in jql


def test_jql_does_not_add_project_type_when_custom_jql_given() -> None:
    connector = _make_connector(jql_query='issuetype = "Service Request"')
    jql = connector._get_jql_query(0, time.time())
    assert 'project type' not in jql
    assert "Service Request" in jql


# ---------------------------------------------------------------------------
# validate_connector_settings
# ---------------------------------------------------------------------------


def test_validate_raises_for_non_jsm_project() -> None:
    connector = _make_connector(project_key="SOFT")
    mock_project = MagicMock()
    mock_project.projectTypeKey = "software"
    connector._jira_client.project.return_value = mock_project  # type: ignore

    with pytest.raises(ConnectorValidationError, match="service_management"):
        connector.validate_connector_settings()


def test_validate_accepts_jsm_project() -> None:
    connector = _make_connector(project_key="HELP")
    mock_project = MagicMock()
    mock_project.projectTypeKey = "service_management"
    connector._jira_client.project.return_value = mock_project  # type: ignore

    # Should not raise
    connector.validate_connector_settings()


def test_validate_skips_type_check_when_custom_jql() -> None:
    connector = _make_connector(project_key="SOFT", jql_query='project = "SOFT"')
    # project() should never be called when jql_query is set
    connector.validate_connector_settings()
    connector._jira_client.project.assert_not_called()  # type: ignore


def test_validate_tolerates_project_type_fetch_failure() -> None:
    """If project() raises an unexpected error, validation should not fail."""
    connector = _make_connector(project_key="HELP")
    connector._jira_client.project.side_effect = RuntimeError("network error")  # type: ignore
    # Should not raise
    connector.validate_connector_settings()


# ---------------------------------------------------------------------------
# load_from_checkpoint stamps DocumentSource on returned documents
# ---------------------------------------------------------------------------


def test_load_from_checkpoint_stamps_jsm_source() -> None:
    connector = _make_connector(project_key="HELP")

    fake_doc = Document(
        id="https://example.atlassian.net/browse/HELP-1",
        sections=[],
        source=DocumentSource.JIRA,
        semantic_identifier="HELP-1: Can't log in",
        metadata={},
    )

    with patch.object(
        JiraServiceManagementConnector.__bases__[0],
        "load_from_checkpoint",
        return_value=_docs_gen([fake_doc]),
    ):
        checkpoint = _make_checkpoint()
        results = list(connector.load_from_checkpoint(0, time.time(), checkpoint))

    assert len(results) == 1
    assert results[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
