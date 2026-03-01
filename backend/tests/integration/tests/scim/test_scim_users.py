"""Integration tests for SCIM user provisioning endpoints.

Covers the full user lifecycle as driven by an IdP (Okta / Azure AD):
1. Create a user via POST /Users
2. Retrieve a user via GET /Users/{id}
3. List, filter, and paginate users via GET /Users
4. Replace a user via PUT /Users/{id}
5. Patch a user (deactivate/reactivate) via PATCH /Users/{id}
6. Delete a user via DELETE /Users/{id}
7. Error cases: missing externalId, duplicate email, not-found, seat limit

All tests are parameterized across IdP request styles:
- **Okta**: lowercase PATCH ops, minimal payloads (core schema only).
- **Entra**: capitalized ops (``"Replace"``), enterprise extension data
  (department, manager), and structured email arrays.

The server normalizes both — these tests verify that all IdP-specific fields
are accepted and round-tripped correctly.

Auth, revoked-token, and service-discovery tests live in test_scim_tokens.py.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
import redis
import requests

from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.license.models import PlanType
from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import REDIS_DB_NUMBER
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PORT
from onyx.server.settings.models import ApplicationStatus
from tests.integration.common_utils.managers.scim_client import ScimClient
from tests.integration.common_utils.managers.scim_token import ScimTokenManager


SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE_USER_SCHEMA = (
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
)
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

_LICENSE_REDIS_KEY = "public:license:metadata"


@pytest.fixture(scope="module", params=["okta", "entra"])
def idp_style(request: pytest.FixtureRequest) -> str:
    """Parameterized IdP style — runs every test with both Okta and Entra request formats."""
    return request.param


@pytest.fixture(scope="module")
def scim_token(idp_style: str) -> str:
    """Create a single SCIM token shared across all tests in this module.

    Creating a new token revokes the previous one, so we create exactly once
    per IdP-style run and reuse. Uses UserManager directly to avoid
    fixture-scope conflicts with the function-scoped admin_user fixture.
    """
    from tests.integration.common_utils.constants import ADMIN_USER_NAME
    from tests.integration.common_utils.constants import GENERAL_HEADERS
    from tests.integration.common_utils.managers.user import build_email
    from tests.integration.common_utils.managers.user import DEFAULT_PASSWORD
    from tests.integration.common_utils.managers.user import UserManager
    from tests.integration.common_utils.test_models import DATestUser

    try:
        admin = UserManager.create(name=ADMIN_USER_NAME)
    except Exception:
        admin = UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email(ADMIN_USER_NAME),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                role=UserRole.ADMIN,
                is_active=True,
            )
        )

    token = ScimTokenManager.create(
        name=f"scim-user-tests-{idp_style}",
        user_performing_action=admin,
    ).raw_token
    assert token is not None
    return token


def _make_user_resource(
    email: str,
    external_id: str,
    given_name: str = "Test",
    family_name: str = "User",
    active: bool = True,
    idp_style: str = "okta",
    department: str | None = None,
    manager_id: str | None = None,
) -> dict:
    """Build a SCIM UserResource payload appropriate for the IdP style.

    Entra sends richer payloads including enterprise extension data (department,
    manager), structured email arrays, and the enterprise schema URN. Okta sends
    minimal payloads with just core user fields.
    """
    resource: dict = {
        "schemas": [SCIM_USER_SCHEMA],
        "userName": email,
        "externalId": external_id,
        "name": {
            "givenName": given_name,
            "familyName": family_name,
        },
        "active": active,
    }
    if idp_style == "entra":
        dept = department or "Engineering"
        mgr = manager_id or "mgr-ext-001"
        resource["schemas"].append(SCIM_ENTERPRISE_USER_SCHEMA)
        resource[SCIM_ENTERPRISE_USER_SCHEMA] = {
            "department": dept,
            "manager": {"value": mgr},
        }
        resource["emails"] = [
            {"value": email, "type": "work", "primary": True},
        ]
    return resource


def _make_patch_request(operations: list[dict], idp_style: str = "okta") -> dict:
    """Build a SCIM PatchOp payload, applying IdP-specific operation casing.

    Entra sends capitalized operations (e.g. ``"Replace"`` instead of
    ``"replace"``). The server's ``normalize_operation`` validator lowercases
    them — these tests verify that both casings are accepted.
    """
    cased_operations = []
    for operation in operations:
        cased = dict(operation)
        if idp_style == "entra":
            cased["op"] = operation["op"].capitalize()
        cased_operations.append(cased)
    return {
        "schemas": [SCIM_PATCH_SCHEMA],
        "Operations": cased_operations,
    }


def _create_scim_user(
    token: str,
    email: str,
    external_id: str,
    idp_style: str = "okta",
) -> requests.Response:
    return ScimClient.post(
        "/Users",
        token,
        json=_make_user_resource(email, external_id, idp_style=idp_style),
    )


def _assert_entra_extension(
    body: dict,
    expected_department: str = "Engineering",
    expected_manager: str = "mgr-ext-001",
) -> None:
    """Assert that Entra enterprise extension fields round-tripped correctly."""
    assert SCIM_ENTERPRISE_USER_SCHEMA in body["schemas"]
    ext = body[SCIM_ENTERPRISE_USER_SCHEMA]
    assert ext["department"] == expected_department
    assert ext["manager"]["value"] == expected_manager


def _assert_entra_emails(body: dict, expected_email: str) -> None:
    """Assert that structured email metadata round-tripped correctly."""
    emails = body["emails"]
    assert len(emails) >= 1
    work_email = next(e for e in emails if e.get("type") == "work")
    assert work_email["value"] == expected_email
    assert work_email["primary"] is True


# ------------------------------------------------------------------
# Lifecycle: create -> get -> list -> replace -> patch -> delete
# ------------------------------------------------------------------


def test_create_user(scim_token: str, idp_style: str) -> None:
    """POST /Users creates a provisioned user and returns 201."""
    email = f"scim_create_{idp_style}@example.com"
    ext_id = f"ext-create-{idp_style}"
    resp = _create_scim_user(scim_token, email, ext_id, idp_style)
    assert resp.status_code == 201

    body = resp.json()
    assert body["userName"] == email
    assert body["externalId"] == ext_id
    assert body["active"] is True
    assert body["id"]  # UUID assigned by server
    assert body["meta"]["resourceType"] == "User"
    assert body["name"]["givenName"] == "Test"
    assert body["name"]["familyName"] == "User"

    if idp_style == "entra":
        _assert_entra_extension(body)
        _assert_entra_emails(body, email)


def test_get_user(scim_token: str, idp_style: str) -> None:
    """GET /Users/{id} returns the user resource with all stored fields."""
    email = f"scim_get_{idp_style}@example.com"
    ext_id = f"ext-get-{idp_style}"
    created = _create_scim_user(scim_token, email, ext_id, idp_style).json()

    resp = ScimClient.get(f"/Users/{created['id']}", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["id"] == created["id"]
    assert body["userName"] == email
    assert body["externalId"] == ext_id
    assert body["name"]["givenName"] == "Test"
    assert body["name"]["familyName"] == "User"

    if idp_style == "entra":
        _assert_entra_extension(body)
        _assert_entra_emails(body, email)


def test_list_users(scim_token: str, idp_style: str) -> None:
    """GET /Users returns a ListResponse containing provisioned users."""
    email = f"scim_list_{idp_style}@example.com"
    _create_scim_user(scim_token, email, f"ext-list-{idp_style}", idp_style)

    resp = ScimClient.get("/Users", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] >= 1
    emails = [r["userName"] for r in body["Resources"]]
    assert email in emails


def test_list_users_pagination(scim_token: str, idp_style: str) -> None:
    """GET /Users with startIndex and count returns correct pagination."""
    _create_scim_user(
        scim_token,
        f"scim_page1_{idp_style}@example.com",
        f"ext-page-1-{idp_style}",
        idp_style,
    )
    _create_scim_user(
        scim_token,
        f"scim_page2_{idp_style}@example.com",
        f"ext-page-2-{idp_style}",
        idp_style,
    )

    resp = ScimClient.get("/Users?startIndex=1&count=1", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["startIndex"] == 1
    assert body["itemsPerPage"] == 1
    assert body["totalResults"] >= 2
    assert len(body["Resources"]) == 1


def test_filter_users_by_username(scim_token: str, idp_style: str) -> None:
    """GET /Users?filter=userName eq '...' returns only matching users."""
    email = f"scim_filter_{idp_style}@example.com"
    _create_scim_user(scim_token, email, f"ext-filter-{idp_style}", idp_style)

    resp = ScimClient.get(f'/Users?filter=userName eq "{email}"', scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["userName"] == email


def test_replace_user(scim_token: str, idp_style: str) -> None:
    """PUT /Users/{id} replaces the user resource including enterprise fields."""
    email = f"scim_replace_{idp_style}@example.com"
    ext_id = f"ext-replace-{idp_style}"
    created = _create_scim_user(scim_token, email, ext_id, idp_style).json()

    updated_resource = _make_user_resource(
        email=email,
        external_id=ext_id,
        given_name="Updated",
        family_name="Name",
        idp_style=idp_style,
        department="Product",
    )
    resp = ScimClient.put(f"/Users/{created['id']}", scim_token, json=updated_resource)
    assert resp.status_code == 200

    body = resp.json()
    assert body["name"]["givenName"] == "Updated"
    assert body["name"]["familyName"] == "Name"

    if idp_style == "entra":
        _assert_entra_extension(body, expected_department="Product")
        _assert_entra_emails(body, email)


def test_patch_deactivate_user(scim_token: str, idp_style: str) -> None:
    """PATCH /Users/{id} with active=false deactivates the user."""
    created = _create_scim_user(
        scim_token,
        f"scim_deactivate_{idp_style}@example.com",
        f"ext-deactivate-{idp_style}",
        idp_style,
    ).json()
    assert created["active"] is True

    resp = ScimClient.patch(
        f"/Users/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "active", "value": False}], idp_style
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    # Confirm via GET
    get_resp = ScimClient.get(f"/Users/{created['id']}", scim_token)
    assert get_resp.json()["active"] is False


def test_patch_reactivate_user(scim_token: str, idp_style: str) -> None:
    """PATCH active=true reactivates a previously deactivated user."""
    created = _create_scim_user(
        scim_token,
        f"scim_reactivate_{idp_style}@example.com",
        f"ext-reactivate-{idp_style}",
        idp_style,
    ).json()

    # Deactivate
    deactivate_resp = ScimClient.patch(
        f"/Users/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "active", "value": False}], idp_style
        ),
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["active"] is False

    # Reactivate
    resp = ScimClient.patch(
        f"/Users/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "active", "value": True}], idp_style
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is True


def test_delete_user(scim_token: str, idp_style: str) -> None:
    """DELETE /Users/{id} deactivates and removes the SCIM mapping."""
    created = _create_scim_user(
        scim_token,
        f"scim_delete_{idp_style}@example.com",
        f"ext-delete-{idp_style}",
        idp_style,
    ).json()

    resp = ScimClient.delete(f"/Users/{created['id']}", scim_token)
    assert resp.status_code == 204

    # Second DELETE returns 404 per RFC 7644 §3.6 (mapping removed)
    resp2 = ScimClient.delete(f"/Users/{created['id']}", scim_token)
    assert resp2.status_code == 404


# ------------------------------------------------------------------
# Error cases
# ------------------------------------------------------------------


def test_create_user_missing_external_id(scim_token: str) -> None:
    """POST /Users without externalId returns 400."""
    resp = ScimClient.post(
        "/Users",
        scim_token,
        json={
            "schemas": [SCIM_USER_SCHEMA],
            "userName": "scim_no_extid@example.com",
            "active": True,
        },
    )
    assert resp.status_code == 400
    assert "externalId" in resp.json()["detail"]


def test_create_user_duplicate_email(scim_token: str, idp_style: str) -> None:
    """POST /Users with an already-taken email returns 409."""
    email = f"scim_dup_{idp_style}@example.com"
    resp1 = _create_scim_user(scim_token, email, f"ext-dup-1-{idp_style}", idp_style)
    assert resp1.status_code == 201

    resp2 = _create_scim_user(scim_token, email, f"ext-dup-2-{idp_style}", idp_style)
    assert resp2.status_code == 409


def test_get_nonexistent_user(scim_token: str) -> None:
    """GET /Users/{bad-id} returns 404."""
    resp = ScimClient.get("/Users/00000000-0000-0000-0000-000000000000", scim_token)
    assert resp.status_code == 404


def test_filter_users_by_external_id(scim_token: str, idp_style: str) -> None:
    """GET /Users?filter=externalId eq '...' returns the matching user."""
    ext_id = f"ext-unique-filter-id-{idp_style}"
    _create_scim_user(
        scim_token, f"scim_extfilter_{idp_style}@example.com", ext_id, idp_style
    )

    resp = ScimClient.get(f'/Users?filter=externalId eq "{ext_id}"', scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["externalId"] == ext_id


# ------------------------------------------------------------------
# Seat-limit enforcement
# ------------------------------------------------------------------


def _seed_license(r: redis.Redis, seats: int) -> None:
    """Write a LicenseMetadata entry into Redis with the given seat cap."""
    now = datetime.now(timezone.utc)
    metadata = LicenseMetadata(
        tenant_id="public",
        organization_name="Test Org",
        seats=seats,
        used_seats=0,  # check_seat_availability recalculates from DB
        plan_type=PlanType.ANNUAL,
        issued_at=now,
        expires_at=now + timedelta(days=365),
        status=ApplicationStatus.ACTIVE,
        source=LicenseSource.MANUAL_UPLOAD,
    )
    r.set(_LICENSE_REDIS_KEY, metadata.model_dump_json(), ex=300)


def test_create_user_seat_limit(scim_token: str, idp_style: str) -> None:
    """POST /Users returns 403 when the seat limit is reached."""
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUMBER)

    # admin_user already occupies 1 seat; cap at 1 -> full
    _seed_license(r, seats=1)

    try:
        resp = _create_scim_user(
            scim_token,
            f"scim_blocked_{idp_style}@example.com",
            f"ext-blocked-{idp_style}",
            idp_style,
        )
        assert resp.status_code == 403
        assert "seat" in resp.json()["detail"].lower()
    finally:
        r.delete(_LICENSE_REDIS_KEY)


def test_reactivate_user_seat_limit(scim_token: str, idp_style: str) -> None:
    """PATCH active=true returns 403 when the seat limit is reached."""
    # Create and deactivate a user (before license is seeded)
    created = _create_scim_user(
        scim_token,
        f"scim_reactivate_blocked_{idp_style}@example.com",
        f"ext-reactivate-blocked-{idp_style}",
        idp_style,
    ).json()
    assert created["active"] is True

    deactivate_resp = ScimClient.patch(
        f"/Users/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "active", "value": False}], idp_style
        ),
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["active"] is False

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_NUMBER)

    # Seed license capped at current active users -> reactivation should fail
    _seed_license(r, seats=1)

    try:
        resp = ScimClient.patch(
            f"/Users/{created['id']}",
            scim_token,
            json=_make_patch_request(
                [{"op": "replace", "path": "active", "value": True}], idp_style
            ),
        )
        assert resp.status_code == 403
        assert "seat" in resp.json()["detail"].lower()
    finally:
        r.delete(_LICENSE_REDIS_KEY)
