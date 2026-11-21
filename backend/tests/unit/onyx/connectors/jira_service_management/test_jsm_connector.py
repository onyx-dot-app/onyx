"""Unit tests for JiraServiceManagementConnector."""

import importlib.util
import logging
import sys
import types
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest


def _ensure_onyx_runtime_stubs() -> None:
    """Stub heavy Onyx-stack dependencies only when not installed locally."""
    if importlib.util.find_spec("fastapi_users") is not None:
        return

    class _DummyBase:
        pass

    fastapi_users = types.ModuleType("fastapi_users")
    fastapi_users_schemas = types.ModuleType("fastapi_users.schemas")
    fastapi_users_schemas.BaseUser = _DummyBase  # type: ignore[attr-defined]
    fastapi_users_schemas.BaseUserCreate = _DummyBase  # type: ignore[attr-defined]
    fastapi_users_schemas.BaseUserUpdate = _DummyBase  # type: ignore[attr-defined]
    sys.modules.setdefault("fastapi_users", fastapi_users)
    sys.modules.setdefault("fastapi_users.schemas", fastapi_users_schemas)

    if importlib.util.find_spec("onyx.configs.app_configs") is None or True:
        app_configs = types.ModuleType("onyx.configs.app_configs")
        app_configs.INDEX_BATCH_SIZE = 100  # type: ignore[attr-defined]
        sys.modules["onyx.configs.app_configs"] = app_configs

    logger_mod = types.ModuleType("onyx.utils.logger")
    logger_mod.setup_logger = lambda *_args, **_kwargs: logging.getLogger("jsm_test")  # type: ignore[attr-defined]
    sys.modules["onyx.utils.logger"] = logger_mod

    retry_mod = types.ModuleType("onyx.utils.retry_wrapper")
    retry_mod.retry_builder = lambda **_kwargs: (lambda fn: fn)  # type: ignore[attr-defined]
    sys.modules["onyx.utils.retry_wrapper"] = retry_mod

    rl_mod = types.ModuleType(
        "onyx.connectors.cross_connector_utils.rate_limit_wrapper"
    )
    rl_mod.rl_requests = MagicMock()  # type: ignore[attr-defined]
    sys.modules["onyx.connectors.cross_connector_utils.rate_limit_wrapper"] = rl_mod

    var_mod = types.ModuleType("onyx.utils.variable_functionality")
    var_mod.fetch_ee_implementation_or_noop = lambda *_a, **_kw: (lambda *_x, **_y: None)  # type: ignore[attr-defined]
    sys.modules["onyx.utils.variable_functionality"] = var_mod

    staging_mod = types.ModuleType("onyx.file_store.staging")
    staging_mod.RawFileCallback = Any  # type: ignore[attr-defined]
    sys.modules["onyx.file_store.staging"] = staging_mod

    hb_mod = types.ModuleType("onyx.indexing.indexing_heartbeat")
    hb_mod.IndexingHeartbeatInterface = Any  # type: ignore[attr-defined]
    sys.modules["onyx.indexing.indexing_heartbeat"] = hb_mod

    access_mod = types.ModuleType("onyx.access.models")
    access_mod.ExternalAccess = Any  # type: ignore[attr-defined]
    sys.modules["onyx.access.models"] = access_mod

    db_enums = types.ModuleType("onyx.db.enums")
    db_enums.HierarchyNodeType = Any  # type: ignore[attr-defined]
    db_enums.IndexModelStatus = Any  # type: ignore[attr-defined]
    sys.modules["onyx.db.enums"] = db_enums

    text_proc = types.ModuleType("onyx.utils.text_processing")
    text_proc.make_url_compatible = lambda s: s  # type: ignore[attr-defined]
    text_proc.shorten = lambda s, *_a, **_kw: s  # type: ignore[attr-defined]
    sys.modules["onyx.utils.text_processing"] = text_proc


_ensure_onyx_runtime_stubs()

from onyx.configs.constants import DocumentSource  # noqa: E402
from onyx.connectors.exceptions import (  # noqa: E402
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import LoadConnector, PollConnector  # noqa: E402
from onyx.connectors.jira_service_management import connector as jsm_module  # noqa: E402
from onyx.connectors.jira_service_management.config import (  # noqa: E402
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (  # noqa: E402
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError  # noqa: E402


def _fake_response(status_code: int, payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


def _sample_ticket(
    issue_key: str,
    summary: str,
    status: str = "Waiting for support",
    status_category: str = "INDETERMINATE",
    created_iso: str = "2026-01-10T10:00:00+00:00",
    status_iso: str = "2026-01-11T12:00:00+00:00",
) -> dict[str, Any]:
    return {
        "issueId": issue_key.split("-")[-1],
        "issueKey": issue_key,
        "serviceDeskId": "1",
        "requestType": {"id": "10", "name": "IT Help"},
        "createdDate": {"iso8601": created_iso},
        "currentStatus": {
            "status": status,
            "statusCategory": status_category,
            "statusDate": {"iso8601": status_iso},
        },
        "reporter": {
            "displayName": "Alice Customer",
            "emailAddress": "alice@example.com",
        },
        "requestFieldValues": [
            {"fieldId": "summary", "label": "Summary", "value": summary},
            {
                "fieldId": "description",
                "label": "Description",
                "value": f"Details for {issue_key}",
            },
            {
                "fieldId": "priority",
                "label": "Priority",
                "value": {"name": "High"},
            },
        ],
        "_links": {"web": f"https://acme.atlassian.net/browse/{issue_key}"},
    }


def test_implements_load_and_poll_connector_contracts() -> None:
    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        project_key="ITSM",
    )
    assert isinstance(connector, LoadConnector)
    assert isinstance(connector, PollConnector)


def test_load_credentials_cloud_and_datacenter() -> None:
    cloud_conn = JiraServiceManagementConnector(base_url="acme.atlassian.net/")
    cloud_conn.load_credentials(
        {"jsm_user_email": "bot@acme.com", "jsm_api_token": "tok-123"}
    )
    auth, headers = cloud_conn._request_auth_and_headers()
    assert cloud_conn.base_url == "https://acme.atlassian.net"
    assert auth == ("bot@acme.com", "tok-123")
    assert "Authorization" not in headers

    dc_conn = JiraServiceManagementConnector()
    dc_conn.load_credentials(
        {
            "jsm_base_url": "https://jsm.internal.corp/",
            "jsm_api_token": "pat-xyz",
        }
    )
    dc_auth, dc_headers = dc_conn._request_auth_and_headers()
    assert dc_conn.base_url == "https://jsm.internal.corp"
    assert dc_auth is None
    assert dc_headers["Authorization"] == "Bearer pat-xyz"


def test_load_credentials_raises_when_missing() -> None:
    conn = JiraServiceManagementConnector(base_url="https://acme.atlassian.net")
    with pytest.raises(ConnectorMissingCredentialError):
        conn.load_credentials({})

    conn_no_url = JiraServiceManagementConnector()
    with pytest.raises(ConnectorMissingCredentialError):
        conn_no_url.load_credentials({"jsm_api_token": "tok-123"})


def test_load_from_state_paginates_tickets_and_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []

    def fake_get(
        url: str,
        headers: dict[str, str],  # noqa: ARG001
        auth: tuple[str, str] | None,  # noqa: ARG001
        params: dict[str, Any] | None = None,
    ) -> MagicMock:
        calls.append((url, params))
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return _fake_response(
                200,
                {
                    "isLastPage": True,
                    "values": [
                        {"id": "1", "projectKey": "ITSM", "projectName": "IT Help"},
                        {"id": "2", "projectKey": "HR", "projectName": "HR Desk"},
                    ],
                },
            )
        if url.endswith("/rest/servicedeskapi/servicedesk/1"):
            return _fake_response(200, {"id": "1", "projectKey": "ITSM"})
        if url.endswith("/rest/servicedeskapi/request"):
            start = (params or {}).get("start", 0)
            if start == 0:
                return _fake_response(
                    200,
                    {
                        "isLastPage": False,
                        "values": [_sample_ticket("ITSM-1", "Laptop won't boot")],
                    },
                )
            if start == 1:
                return _fake_response(
                    200,
                    {
                        "isLastPage": True,
                        "values": [
                            _sample_ticket(
                                "ITSM-2",
                                "VPN access",
                                status="Resolved",
                                status_category="DONE",
                                created_iso="2026-01-12T08:00:00+00:00",
                                status_iso="2026-01-13T09:30:00+00:00",
                            )
                        ],
                    },
                )
            raise AssertionError(f"Unexpected pagination start offset: {start}")
        if url.endswith("/rest/servicedeskapi/request/ITSM-1/comment"):
            return _fake_response(
                200,
                {
                    "isLastPage": True,
                    "values": [
                        {
                            "id": "100",
                            "body": "Public reply from agent",
                            "public": True,
                            "author": {"displayName": "Agent Bob"},
                            "created": {"iso8601": "2026-01-11T15:00:00+00:00"},
                        },
                        {
                            "id": "101",
                            "body": "Internal escalation note",
                            "public": False,
                            "author": {"displayName": "Agent Bob"},
                            "created": {"iso8601": "2026-01-11T16:00:00+00:00"},
                        },
                    ],
                },
            )
        if url.endswith("/rest/servicedeskapi/request/ITSM-2/comment"):
            return _fake_response(200, {"isLastPage": True, "values": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(jsm_module, "_rate_limited_jsm_get", fake_get)

    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        project_key="ITSM",
        include_internal_comments=False,
        batch_size=1,
    )
    connector.load_credentials(
        {"jsm_user_email": "bot@acme.com", "jsm_api_token": "tok"}
    )

    batches = list(connector.load_from_state())
    assert len(batches) == 2

    doc1 = batches[0][0]
    assert doc1.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc1.id == "JSM_1"
    assert doc1.semantic_identifier == "ITSM-1: Laptop won't boot"
    assert doc1.metadata["status"] == "Waiting for support"
    assert doc1.metadata["status_category"] == "INDETERMINATE"
    assert doc1.metadata["priority"] == "High"
    assert doc1.metadata["project_key"] == "ITSM"
    assert doc1.metadata["comment_count"] == "1"
    assert doc1.primary_owners is not None
    assert doc1.primary_owners[0].email == "alice@example.com"
    assert "Public reply from agent" in doc1.sections[0].text
    assert "Internal escalation note" not in doc1.sections[0].text
    assert doc1.doc_created_at == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    # Public comment at 15:00 is newer than statusDate 12:00.
    assert doc1.doc_updated_at == datetime(2026, 1, 11, 15, 0, tzinfo=timezone.utc)

    doc2 = batches[1][0]
    assert doc2.metadata["status"] == "Resolved"
    assert doc2.metadata["status_category"] == "DONE"
    assert doc2.doc_updated_at == datetime(2026, 1, 13, 9, 30, tzinfo=timezone.utc)


def test_include_internal_comments_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(
        url: str,
        headers: dict[str, str],  # noqa: ARG001
        auth: tuple[str, str] | None,  # noqa: ARG001
        params: dict[str, Any] | None = None,  # noqa: ARG001
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/1"):
            return _fake_response(200, {"id": "1", "projectKey": "ITSM"})
        if url.endswith("/rest/servicedeskapi/request"):
            return _fake_response(
                200,
                {
                    "isLastPage": True,
                    "values": [_sample_ticket("ITSM-9", "Internal test")],
                },
            )
        if url.endswith("/rest/servicedeskapi/request/ITSM-9/comment"):
            return _fake_response(
                200,
                {
                    "isLastPage": True,
                    "values": [
                        {
                            "id": "201",
                            "body": "Secret internal note",
                            "public": False,
                            "author": {"displayName": "Agent Eve"},
                            "created": {"epochMillis": 1768147200000},
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(jsm_module, "_rate_limited_jsm_get", fake_get)

    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        service_desk_id="1",
        include_internal_comments=True,
    )
    connector.load_credentials({"jsm_api_token": "pat"})
    docs = [d for batch in connector.load_from_state() for d in batch]
    assert len(docs) == 1
    assert docs[0].metadata["comment_count"] == "1"
    assert "Secret internal note" in docs[0].sections[0].text


def test_poll_source_filters_by_time_window(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(
        url: str,
        headers: dict[str, str],  # noqa: ARG001
        auth: tuple[str, str] | None,  # noqa: ARG001
        params: dict[str, Any] | None = None,  # noqa: ARG001
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/1"):
            return _fake_response(200, {"id": "1", "projectKey": "ITSM"})
        if url.endswith("/rest/servicedeskapi/request"):
            return _fake_response(
                200,
                {
                    "isLastPage": True,
                    "values": [
                        _sample_ticket(
                            "ITSM-10",
                            "Old ticket",
                            created_iso="2026-01-01T00:00:00+00:00",
                            status_iso="2026-01-02T00:00:00+00:00",
                        ),
                        _sample_ticket(
                            "ITSM-11",
                            "In-window ticket",
                            created_iso="2026-01-10T00:00:00+00:00",
                            status_iso="2026-01-15T12:00:00+00:00",
                        ),
                    ],
                },
            )
        if "/comment" in url:
            return _fake_response(200, {"isLastPage": True, "values": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(jsm_module, "_rate_limited_jsm_get", fake_get)

    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        service_desk_id="1",
    )
    connector.load_credentials({"jsm_api_token": "pat"})

    start = datetime(2026, 1, 14, 0, 0, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc).timestamp()
    docs = [d for batch in connector.poll_source(start, end) for d in batch]

    assert [d.metadata["issue_key"] for d in docs] == ["ITSM-11"]


def test_unknown_project_and_auth_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_missing_project(
        url: str,  # noqa: ARG001
        headers: dict[str, str],  # noqa: ARG001
        auth: tuple[str, str] | None,  # noqa: ARG001
        params: dict[str, Any] | None = None,  # noqa: ARG001
    ) -> MagicMock:
        return _fake_response(
            200,
            {"isLastPage": True, "values": [{"id": "1", "projectKey": "OTHER"}]},
        )

    monkeypatch.setattr(jsm_module, "_rate_limited_jsm_get", fake_missing_project)
    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net", project_key="MISSING"
    )
    connector.load_credentials({"jsm_api_token": "pat"})
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()

    monkeypatch.setattr(
        jsm_module,
        "_rate_limited_jsm_get",
        lambda *_a, **_kw: _fake_response(401, {}),
    )
    with pytest.raises(CredentialExpiredError):
        connector.validate_connector_settings()

    monkeypatch.setattr(
        jsm_module,
        "_rate_limited_jsm_get",
        lambda *_a, **_kw: _fake_response(403, {}),
    )
    with pytest.raises(InsufficientPermissionsError):
        connector.validate_connector_settings()


def test_connector_config_defaults() -> None:
    from onyx.configs.app_configs import INDEX_BATCH_SIZE

    cfg = JiraServiceManagementConnectorConfig(
        base_url="https://acme.atlassian.net", project_key="ITSM"
    )
    assert cfg.project_key == "ITSM"
    assert cfg.include_internal_comments is False
    assert cfg.batch_size == INDEX_BATCH_SIZE


def test_explicit_service_desk_validates_credentials_and_project_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        project_key="ITSM",
        service_desk_id="2",
    )
    connector.load_credentials(
        {
            "jsm_user_email": "bot@acme.com",
            "jsm_api_token": "secret",
        }
    )

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        lambda *_args, **_kwargs: _fake_response(
            200, {"id": "2", "projectKey": "HR"}
        ),
    )
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()

    def fake_missing_key_unresolved(
        url: str, *_args: Any, **_kwargs: Any
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/2"):
            return _fake_response(200, {"id": "2"})
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return _fake_response(200, {"isLastPage": True, "values": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        fake_missing_key_unresolved,
    )
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()

    def fake_missing_key_resolved_by_project_id(
        url: str, *_args: Any, **_kwargs: Any
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/2"):
            return _fake_response(200, {"id": "2", "projectId": "10002"})
        if url.endswith("/rest/api/2/project/10002"):
            return _fake_response(200, {"id": "10002", "key": "ITSM"})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        fake_missing_key_resolved_by_project_id,
    )
    connector.validate_connector_settings()

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        lambda *_args, **_kwargs: _fake_response(
            200, {"id": "2", "projectKey": "itsm"}
        ),
    )
    connector.validate_connector_settings()

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        lambda *_args, **_kwargs: _fake_response(401, {}),
    )
    with pytest.raises(CredentialExpiredError):
        connector.validate_connector_settings()


def test_explicit_service_desk_project_lookup_insufficient_permissions_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        project_key="ITSM",
        service_desk_id="2",
    )
    connector.load_credentials(
        {
            "jsm_user_email": "bot@acme.com",
            "jsm_api_token": "secret",
        }
    )

    def fake_project_403_fallback_match(
        url: str, *_args: Any, **_kwargs: Any
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/2"):
            return _fake_response(200, {"id": "2", "projectId": "10002"})
        if url.endswith("/rest/api/2/project/10002"):
            return _fake_response(403, {})
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return _fake_response(
                200, {"isLastPage": True, "values": [{"id": "2", "projectKey": "ITSM"}]}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        fake_project_403_fallback_match,
    )
    assert connector._resolve_service_desks() == [("2", "ITSM")]
    connector.validate_connector_settings()

    def fake_project_403_fallback_mismatch(
        url: str, *_args: Any, **_kwargs: Any
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/2"):
            return _fake_response(200, {"id": "2", "projectId": "10002"})
        if url.endswith("/rest/api/2/project/10002"):
            return _fake_response(403, {})
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return _fake_response(
                200, {"isLastPage": True, "values": [{"id": "2", "projectKey": "HR"}]}
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        fake_project_403_fallback_mismatch,
    )
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()

    connector_no_project = JiraServiceManagementConnector(
        base_url="https://acme.atlassian.net",
        service_desk_id="2",
    )
    connector_no_project.load_credentials(
        {
            "jsm_user_email": "bot@acme.com",
            "jsm_api_token": "secret",
        }
    )

    def fake_project_403_no_project_key(
        url: str, *_args: Any, **_kwargs: Any
    ) -> MagicMock:
        if url.endswith("/rest/servicedeskapi/servicedesk/2"):
            return _fake_response(200, {"id": "2", "projectId": "10002"})
        if url.endswith("/rest/api/2/project/10002"):
            return _fake_response(403, {})
        if url.endswith("/rest/servicedeskapi/servicedesk"):
            return _fake_response(200, {"isLastPage": True, "values": [{"id": "2"}]})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector._rate_limited_jsm_get",
        fake_project_403_no_project_key,
    )
    assert connector_no_project._resolve_service_desks() == [("2", None)]
