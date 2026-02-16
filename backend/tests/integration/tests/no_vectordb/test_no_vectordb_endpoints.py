"""Integration tests for endpoint gating when DISABLE_VECTOR_DB is set.

Vector-DB-dependent endpoints should return HTTP 501.
Non-dependent endpoints (settings, document sets, chat, etc.) should work
normally.
"""

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------


def _headers(user: DATestUser) -> dict[str, str]:
    return user.headers if user else {"Content-Type": "application/json"}


# ------------------------------------------------------------------
# Gated endpoints — should return 501
# ------------------------------------------------------------------


def test_admin_search_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.post(
        f"{API_SERVER_URL}/admin/search",
        json={"query": "test", "filters": {}},
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501, f"Expected 501, got {resp.status_code}"


def test_document_size_info_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.get(
        f"{API_SERVER_URL}/document/document-size-info",
        params={"document_id": "fake-doc"},
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


def test_document_chunk_info_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.get(
        f"{API_SERVER_URL}/document/chunk-info",
        params={"document_id": "fake-doc"},
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


def test_set_new_search_settings_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.post(
        f"{API_SERVER_URL}/search-settings/set-new-search-settings",
        json={},
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


def test_cancel_new_embedding_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.post(
        f"{API_SERVER_URL}/search-settings/cancel-new-embedding",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


def test_connector_router_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    """The entire /manage router is gated — any connector endpoint should 501."""
    resp = requests.get(
        f"{API_SERVER_URL}/manage/connector",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


def test_ingestion_post_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.post(
        f"{API_SERVER_URL}/onyx-api/ingestion",
        json={"document": {}},
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


def test_ingestion_delete_returns_501(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.delete(
        f"{API_SERVER_URL}/onyx-api/ingestion/fake-doc-id",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 501


# ------------------------------------------------------------------
# Non-gated endpoints — should work (2xx)
# ------------------------------------------------------------------


def test_settings_endpoint_works(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.get(
        f"{API_SERVER_URL}/settings",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vector_db_enabled"] is False


def test_document_set_list_works(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.get(
        f"{API_SERVER_URL}/manage/document-set",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 200


def test_persona_list_works(
    reset: None, admin_user: DATestUser  # noqa: ARG001
) -> None:
    resp = requests.get(
        f"{API_SERVER_URL}/admin/persona",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 200


def test_tool_list_works(reset: None, admin_user: DATestUser) -> None:  # noqa: ARG001
    resp = requests.get(
        f"{API_SERVER_URL}/tool",
        headers=_headers(admin_user),
    )
    assert resp.status_code == 200
    tools = resp.json()
    tool_ids = {t["in_code_tool_id"] for t in tools if t.get("in_code_tool_id")}
    assert (
        "FileReaderTool" in tool_ids
    ), "FileReaderTool should be registered as a built-in tool"
