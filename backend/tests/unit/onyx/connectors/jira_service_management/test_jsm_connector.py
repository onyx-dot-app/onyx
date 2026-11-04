"""Unit tests for the Jira Service Management connector.

These cover the behaviour that differs from the Jira connector, plus the
contract violations that broke earlier JSM attempts:

- the gateway registers, and every public operation is classified
- the connector wires the JSM gateway, not the Jira one
- a request gains its service desk and request type
- a missing agent licence degrades instead of failing the run
- the document reports the JSM source
- the project key is validated (including a trailing newline)
"""

from typing import Any, cast

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _request_type_id,
)
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
    JsmApiError,
)
from onyx.connectors.source_operations import get_source_operations_class

_BASE_URL = "https://example.atlassian.net"
_PROJECT = "SUPPORT"


def _issue(
    *,
    key: str = "SUPPORT-1",
    summary: str = "Cannot log in",
    request_type_id: str | None = "10",
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": summary,
        "updated": "2026-01-01T12:00:00.000+0000",
        "created": "2026-01-01T12:00:00.000+0000",
        "description": "The portal login fails.",
        "labels": [],
        "reporter": {"displayName": "Ada", "emailAddress": "ada@example.com"},
        "assignee": {"displayName": "Grace", "emailAddress": "grace@example.com"},
        "status": {"name": "Open"},
        "project": {"key": _PROJECT, "name": "Support"},
        "issuetype": {"name": "Service request"},
        "comment": {"comments": []},
    }
    if request_type_id is not None:
        # JSM keeps the request type in a custom field, whose id differs per
        # site. The connector finds it by shape, not by id.
        fields["customfield_10010"] = {
            "requestType": {"id": request_type_id, "name": "Get IT help"}
        }
    return {"id": key.split("-")[-1], "key": key, "fields": fields}


@pytest.fixture
def connector() -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(jira_base_url=_BASE_URL, project_key=_PROJECT)


# --------------------------------------------------------------- registration


def test_gateway_is_registered_for_the_jsm_source() -> None:
    registered = get_source_operations_class(DocumentSource.JIRA_SERVICE_MANAGEMENT)
    assert registered is JiraServiceManagementSourceOperations


def test_gateway_classifies_every_public_operation() -> None:
    """A gateway that leaves a public method unclassified fails at import, but
    this asserts the operations the indexing path needs are present."""
    specs = JiraServiceManagementSourceOperations.operation_specs()
    assert {
        "get_myself",
        "get_project",
        "get_service_desk",
        "get_request_type",
        "search_issue_ids",
        "bulk_fetch_issues",
        "search_issues",
    } <= set(specs)


def test_config_requires_a_project_key() -> None:
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig.model_validate(
            {"jira_base_url": _BASE_URL}
        )


def test_project_key_rejects_a_trailing_newline() -> None:
    # ``$`` in a regex also matches before a trailing newline; this must not.
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig(
            jira_base_url=_BASE_URL, project_key="SUPPORT\n"
        )


def test_project_key_rejects_lower_case() -> None:
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig(
            jira_base_url=_BASE_URL, project_key="support"
        )


# ------------------------------------------------------------- credential wiring


def test_load_credentials_wires_the_jsm_gateway(
    connector: JiraServiceManagementConnector,
) -> None:
    """The inherited ``load_credentials`` builds a *Jira* gateway. JSM must
    override it, or the servicedeskapi operations are missing at run time."""
    connector.load_credentials(
        {"jira_api_token": "token", "jira_user_email": "a@b.com"}
    )
    assert isinstance(
        connector._source_operations, JiraServiceManagementSourceOperations
    )


# ------------------------------------------------------------------ enrichment


class _FakeGateway:
    """The two servicedeskapi operations the enrichment calls."""

    def __init__(
        self,
        *,
        desk: dict[str, Any] | None = None,
        request_type: dict[str, Any] | None = None,
        desk_error: Exception | None = None,
    ) -> None:
        self._desk = desk
        self._request_type = request_type
        self._desk_error = desk_error
        self.desk_calls = 0

    def get_service_desk(self, *, project_key: str) -> dict[str, Any]:  # noqa: ARG002
        self.desk_calls += 1
        if self._desk_error is not None:
            raise self._desk_error
        return self._desk or {}

    def get_request_type(
        self,
        *,
        service_desk_id: str,  # noqa: ARG002
        request_type_id: str,  # noqa: ARG002
    ) -> dict[str, Any]:
        return self._request_type or {}


def _document_of(
    connector: JiraServiceManagementConnector, issue: dict[str, Any]
) -> Any:
    from onyx.connectors.models import Document

    for item in connector._issue_to_items(issue, set(), False):
        if isinstance(item, Document):
            return item
    return None


def test_request_gains_its_service_desk_and_request_type(
    connector: JiraServiceManagementConnector,
) -> None:
    connector._source_operations = cast(
        Any,
        _FakeGateway(
            desk={"id": "5", "projectName": "IT Support"},
            request_type={"name": "Get IT help"},
        ),
    )
    document = _document_of(connector, _issue())

    assert document is not None
    assert document.metadata["service_desk"] == "IT Support"
    assert document.metadata["request_type"] == "Get IT help"
    assert document.sections[0].text.startswith(
        "Service desk: IT Support\nRequest type: Get IT help\n"
    )


def test_document_reports_the_jsm_source(
    connector: JiraServiceManagementConnector,
) -> None:
    connector._source_operations = cast(
        Any,
        _FakeGateway(
            desk={"id": "5", "projectName": "IT Support"},
            request_type={"name": "Get IT help"},
        ),
    )
    document = _document_of(connector, _issue())

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_missing_agent_licence_still_indexes_the_request(
    connector: JiraServiceManagementConnector,
) -> None:
    """A portal-only account gets an error from servicedeskapi. The request
    must still index, without the extra metadata."""
    connector._source_operations = cast(
        Any, _FakeGateway(desk_error=JsmApiError("no agent licence", status_code=403))
    )
    document = _document_of(connector, _issue())

    assert document is not None
    assert "service_desk" not in document.metadata
    assert document.sections[0].text.startswith("The portal login fails.")


def test_the_service_desk_is_read_once_per_run(
    connector: JiraServiceManagementConnector,
) -> None:
    """A run builds many documents; the service desk must not be fetched per
    document."""
    gateway = _FakeGateway(
        desk={"id": "5", "projectName": "IT Support"},
        request_type={"name": "Get IT help"},
    )
    connector._source_operations = cast(Any, gateway)

    _document_of(connector, _issue(key="SUPPORT-1"))
    _document_of(connector, _issue(key="SUPPORT-2"))

    assert gateway.desk_calls == 1


def test_metadata_can_be_switched_off() -> None:
    quiet = JiraServiceManagementConnector(
        jira_base_url=_BASE_URL,
        project_key=_PROJECT,
        include_service_desk_metadata=False,
    )
    quiet._source_operations = cast(
        Any, _FakeGateway(desk={"id": "5", "projectName": "IT Support"})
    )
    document = _document_of(quiet, _issue())

    assert document is not None
    assert "service_desk" not in document.metadata


def test_request_type_id_reads_the_custom_field_by_shape() -> None:
    assert _request_type_id(_issue(request_type_id="42")) == "42"


def test_request_type_id_absent_when_the_field_is_missing() -> None:
    assert _request_type_id(_issue(request_type_id=None)) is None


def test_request_type_id_tolerates_a_non_dict_fields() -> None:
    assert _request_type_id({"fields": "not-a-dict"}) is None


def test_the_index_query_is_scoped_to_the_service_desk(
    connector: JiraServiceManagementConnector,
) -> None:
    """A service desk connector must never index another project."""
    jql = connector._get_jql_query(0, 1_700_000_000)

    assert 'project = "SUPPORT"' in jql
    assert "updated >=" in jql


def test_a_custom_jql_narrows_within_the_project(
    connector: JiraServiceManagementConnector,
) -> None:
    connector.jql_query = 'requestType = "Get IT help"'

    jql = connector._get_jql_query(0, 1_700_000_000)

    assert 'requestType = "Get IT help"' in jql
