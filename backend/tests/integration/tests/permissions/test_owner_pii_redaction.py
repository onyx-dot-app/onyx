"""Integration tests for owner-email / internal-URL redaction (ENG-4251).

Persona and MCP-server snapshots returned by the basic-access surfaces leaked
PII (the owner's email) and internal infrastructure detail (the MCP
`server_url`) to any authenticated user. These tests verify that:

* the owner email is blanked for non-owner / non-admin callers, while
* the owner (and an admin) still sees the real values.
"""

from uuid import uuid4

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def _find_persona(entries: list[dict], persona_id: int) -> dict:
    return next(entry for entry in entries if entry["id"] == persona_id)


def _find_mcp_server(payload: dict, server_id: int) -> dict:
    return next(s for s in payload["mcp_servers"] if s["id"] == server_id)


def test_persona_owner_email_redacted_for_non_owner(
    permission_admin_user: DATestUser,
    permission_basic_user: DATestUser,
) -> None:
    """`GET /api/persona` must not expose the owner email to non-owner users."""
    persona = PersonaManager.create(
        name=f"pii-redaction-persona-{uuid4()}",
        is_public=True,
        user_performing_action=permission_admin_user,
    )

    # The owner (admin here) still sees their own email.
    admin_resp = client.get(
        f"{API_SERVER_URL}/persona",
        headers=permission_admin_user.headers,
        cookies=permission_admin_user.cookies,
        timeout=30,
    )
    admin_resp.raise_for_status()
    admin_entry = _find_persona(admin_resp.json(), persona.id)
    assert admin_entry["owner"] is not None
    assert admin_entry["owner"]["email"] == permission_admin_user.email

    # A basic, non-owner user sees the persona and its owner id (needed for
    # ownership / creator filtering) but NOT the owner email.
    basic_resp = client.get(
        f"{API_SERVER_URL}/persona",
        headers=permission_basic_user.headers,
        cookies=permission_basic_user.cookies,
        timeout=30,
    )
    basic_resp.raise_for_status()
    basic_entry = _find_persona(basic_resp.json(), persona.id)
    assert basic_entry["owner"] is not None
    assert basic_entry["owner"]["id"]
    assert basic_entry["owner"]["email"] == ""


def test_mcp_server_details_redacted_for_non_owner(
    permission_admin_user: DATestUser,
    permission_basic_user: DATestUser,
) -> None:
    """`GET /api/mcp/servers` must not expose server_url / owner to non-owners."""
    internal_url = f"http://mcp-internal-{uuid4().hex[:8]}.svc.internal/sse"
    server_name = f"pii-redaction-mcp-{uuid4()}"

    create_resp = client.post(
        f"{API_SERVER_URL}/admin/mcp/server",
        json={"name": server_name, "server_url": internal_url},
        headers=permission_admin_user.headers,
        cookies=permission_admin_user.cookies,
        timeout=30,
    )
    create_resp.raise_for_status()
    server_id = create_resp.json()["id"]

    # The owner (admin here) still sees the internal url and owner email.
    admin_resp = client.get(
        f"{API_SERVER_URL}/mcp/servers",
        headers=permission_admin_user.headers,
        cookies=permission_admin_user.cookies,
        timeout=30,
    )
    admin_resp.raise_for_status()
    admin_entry = _find_mcp_server(admin_resp.json(), server_id)
    assert admin_entry["server_url"] == internal_url
    assert admin_entry["owner"] == permission_admin_user.email

    # A basic, non-owner user sees the server entry but neither sensitive field.
    basic_resp = client.get(
        f"{API_SERVER_URL}/mcp/servers",
        headers=permission_basic_user.headers,
        cookies=permission_basic_user.cookies,
        timeout=30,
    )
    basic_resp.raise_for_status()
    basic_entry = _find_mcp_server(basic_resp.json(), server_id)
    assert basic_entry["server_url"] == ""
    assert basic_entry["owner"] == ""
