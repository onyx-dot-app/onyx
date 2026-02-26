"""Integration tests for SCIM group provisioning endpoints.

Covers the full group lifecycle as driven by an IdP (Okta / Azure AD):
1. Create a group via POST /Groups
2. Retrieve a group via GET /Groups/{id}
3. List, filter, and paginate groups via GET /Groups
4. Replace a group via PUT /Groups/{id}
5. Patch a group (add/remove members, rename) via PATCH /Groups/{id}
6. Delete a group via DELETE /Groups/{id}
7. Error cases: duplicate name, not-found, invalid member IDs

All tests are parameterized across IdP request styles (Okta sends lowercase
PATCH ops; Entra sends capitalized ops like ``"Replace"``). The server
normalizes both — these tests verify that.

Auth tests live in test_scim_tokens.py.
User lifecycle tests live in test_scim_users.py.
"""

import pytest
import requests

from onyx.auth.schemas import UserRole
from tests.integration.common_utils.managers.scim_client import ScimClient
from tests.integration.common_utils.managers.scim_token import ScimTokenManager


SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


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
        name=f"scim-group-tests-{idp_style}",
        user_performing_action=admin,
    ).raw_token
    assert token is not None
    return token


def _make_group_resource(
    display_name: str,
    external_id: str | None = None,
    members: list[dict] | None = None,
) -> dict:
    """Build a minimal SCIM GroupResource payload."""
    resource: dict = {
        "schemas": [SCIM_GROUP_SCHEMA],
        "displayName": display_name,
    }
    if external_id is not None:
        resource["externalId"] = external_id
    if members is not None:
        resource["members"] = members
    return resource


def _make_user_resource(email: str, external_id: str) -> dict:
    """Build a minimal SCIM UserResource payload for member creation."""
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "userName": email,
        "externalId": external_id,
        "name": {"givenName": "Test", "familyName": "User"},
        "active": True,
    }


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


def _create_scim_user(token: str, email: str, external_id: str) -> requests.Response:
    return ScimClient.post(
        "/Users", token, json=_make_user_resource(email, external_id)
    )


def _create_scim_group(
    token: str,
    display_name: str,
    external_id: str | None = None,
    members: list[dict] | None = None,
) -> requests.Response:
    return ScimClient.post(
        "/Groups",
        token,
        json=_make_group_resource(display_name, external_id, members),
    )


# ------------------------------------------------------------------
# Lifecycle: create → get → list → replace → patch → delete
# ------------------------------------------------------------------


def test_create_group(scim_token: str, idp_style: str) -> None:
    """POST /Groups creates a group and returns 201."""
    name = f"Engineering {idp_style}"
    resp = _create_scim_group(scim_token, name, external_id="ext-eng-1")
    assert resp.status_code == 201

    body = resp.json()
    assert body["displayName"] == name
    assert body["externalId"] == "ext-eng-1"
    assert body["id"]  # integer ID assigned by server
    assert body["meta"]["resourceType"] == "Group"


def test_create_group_with_members(scim_token: str, idp_style: str) -> None:
    """POST /Groups with members populates the member list."""
    user = _create_scim_user(
        scim_token, f"grp_member1_{idp_style}@example.com", "ext-gm-1"
    ).json()

    resp = _create_scim_group(
        scim_token,
        f"Backend Team {idp_style}",
        external_id="ext-backend-1",
        members=[{"value": user["id"]}],
    )
    assert resp.status_code == 201

    body = resp.json()
    member_ids = [m["value"] for m in body["members"]]
    assert user["id"] in member_ids


def test_get_group(scim_token: str, idp_style: str) -> None:
    """GET /Groups/{id} returns the group resource including members."""
    user = _create_scim_user(
        scim_token, f"grp_get_m_{idp_style}@example.com", "ext-ggm-1"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Frontend Team {idp_style}",
        external_id="ext-fe-1",
        members=[{"value": user["id"]}],
    ).json()

    resp = ScimClient.get(f"/Groups/{created['id']}", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["id"] == created["id"]
    assert body["displayName"] == f"Frontend Team {idp_style}"
    assert body["externalId"] == "ext-fe-1"
    member_ids = [m["value"] for m in body["members"]]
    assert user["id"] in member_ids


def test_list_groups(scim_token: str, idp_style: str) -> None:
    """GET /Groups returns a ListResponse containing provisioned groups."""
    name = f"DevOps Team {idp_style}"
    _create_scim_group(scim_token, name, external_id="ext-devops-1")

    resp = ScimClient.get("/Groups", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] >= 1
    names = [r["displayName"] for r in body["Resources"]]
    assert name in names


def test_list_groups_pagination(scim_token: str, idp_style: str) -> None:
    """GET /Groups with startIndex and count returns correct pagination."""
    _create_scim_group(
        scim_token, f"Page Group A {idp_style}", external_id="ext-page-a"
    )
    _create_scim_group(
        scim_token, f"Page Group B {idp_style}", external_id="ext-page-b"
    )

    resp = ScimClient.get("/Groups?startIndex=1&count=1", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["startIndex"] == 1
    assert body["itemsPerPage"] == 1
    assert body["totalResults"] >= 2
    assert len(body["Resources"]) == 1


def test_filter_groups_by_display_name(scim_token: str, idp_style: str) -> None:
    """GET /Groups?filter=displayName eq '...' returns only matching groups."""
    name = f"Unique QA Team {idp_style}"
    _create_scim_group(scim_token, name, external_id="ext-qa-filter")

    resp = ScimClient.get(f'/Groups?filter=displayName eq "{name}"', scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["displayName"] == name


def test_filter_groups_by_external_id(scim_token: str, idp_style: str) -> None:
    """GET /Groups?filter=externalId eq '...' returns the matching group."""
    ext_id = f"ext-unique-group-id-{idp_style}"
    _create_scim_group(
        scim_token, f"ExtId Filter Group {idp_style}", external_id=ext_id
    )

    resp = ScimClient.get(f'/Groups?filter=externalId eq "{ext_id}"', scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["externalId"] == ext_id


def test_replace_group(scim_token: str, idp_style: str) -> None:
    """PUT /Groups/{id} replaces the group resource."""
    created = _create_scim_group(
        scim_token, f"Original Name {idp_style}", external_id="ext-replace-g"
    ).json()

    user = _create_scim_user(
        scim_token, f"grp_replace_m_{idp_style}@example.com", "ext-grm-1"
    ).json()

    updated_resource = _make_group_resource(
        display_name=f"Renamed Group {idp_style}",
        external_id="ext-replace-g",
        members=[{"value": user["id"]}],
    )
    resp = ScimClient.put(f"/Groups/{created['id']}", scim_token, json=updated_resource)
    assert resp.status_code == 200

    body = resp.json()
    assert body["displayName"] == f"Renamed Group {idp_style}"
    member_ids = [m["value"] for m in body["members"]]
    assert user["id"] in member_ids


def test_replace_group_clears_members(scim_token: str, idp_style: str) -> None:
    """PUT /Groups/{id} with empty members removes all memberships."""
    user = _create_scim_user(
        scim_token, f"grp_clear_m_{idp_style}@example.com", "ext-gcm-1"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Clear Members Group {idp_style}",
        external_id="ext-clear-g",
        members=[{"value": user["id"]}],
    ).json()

    assert len(created["members"]) == 1

    resp = ScimClient.put(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_group_resource(
            f"Clear Members Group {idp_style}", "ext-clear-g", members=[]
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["members"] == []


def test_patch_add_member(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} with op=add adds a member."""
    created = _create_scim_group(
        scim_token, f"Patch Add Group {idp_style}", external_id="ext-patch-add"
    ).json()
    user = _create_scim_user(
        scim_token, f"grp_patch_add_{idp_style}@example.com", "ext-gpa-1"
    ).json()

    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "add", "path": "members", "value": [{"value": user["id"]}]}],
            idp_style,
        ),
    )
    assert resp.status_code == 200

    member_ids = [m["value"] for m in resp.json()["members"]]
    assert user["id"] in member_ids


def test_patch_remove_member(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} with op=remove removes a specific member."""
    user = _create_scim_user(
        scim_token, f"grp_patch_rm_{idp_style}@example.com", "ext-gpr-1"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Patch Remove Group {idp_style}",
        external_id="ext-patch-rm",
        members=[{"value": user["id"]}],
    ).json()
    assert len(created["members"]) == 1

    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [
                {
                    "op": "remove",
                    "path": f'members[value eq "{user["id"]}"]',
                }
            ],
            idp_style,
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["members"] == []


def test_patch_replace_members(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} with op=replace on members swaps the entire list."""
    user_a = _create_scim_user(
        scim_token, f"grp_repl_a_{idp_style}@example.com", "ext-gra-1"
    ).json()
    user_b = _create_scim_user(
        scim_token, f"grp_repl_b_{idp_style}@example.com", "ext-grb-1"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Patch Replace Group {idp_style}",
        external_id="ext-patch-repl",
        members=[{"value": user_a["id"]}],
    ).json()

    # Replace member list: swap A for B
    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [
                {
                    "op": "replace",
                    "path": "members",
                    "value": [{"value": user_b["id"]}],
                }
            ],
            idp_style,
        ),
    )
    assert resp.status_code == 200

    member_ids = [m["value"] for m in resp.json()["members"]]
    assert user_b["id"] in member_ids
    assert user_a["id"] not in member_ids


def test_patch_rename_group(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} with op=replace on displayName renames the group."""
    created = _create_scim_group(
        scim_token,
        f"Old Group Name {idp_style}",
        external_id="ext-rename-g",
    ).json()

    new_name = f"New Group Name {idp_style}"
    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "displayName", "value": new_name}],
            idp_style,
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["displayName"] == new_name

    # Confirm via GET
    get_resp = ScimClient.get(f"/Groups/{created['id']}", scim_token)
    assert get_resp.json()["displayName"] == new_name


def test_delete_group(scim_token: str, idp_style: str) -> None:
    """DELETE /Groups/{id} removes the group."""
    created = _create_scim_group(
        scim_token,
        f"Delete Me Group {idp_style}",
        external_id="ext-del-g",
    ).json()

    resp = ScimClient.delete(f"/Groups/{created['id']}", scim_token)
    assert resp.status_code == 204

    # Second DELETE returns 404 (group hard-deleted)
    resp2 = ScimClient.delete(f"/Groups/{created['id']}", scim_token)
    assert resp2.status_code == 404


def test_delete_group_preserves_members(scim_token: str, idp_style: str) -> None:
    """DELETE /Groups/{id} removes memberships but does not deactivate users."""
    user = _create_scim_user(
        scim_token, f"grp_del_member_{idp_style}@example.com", "ext-gdm-1"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Delete With Members {idp_style}",
        external_id="ext-del-wm",
        members=[{"value": user["id"]}],
    ).json()

    resp = ScimClient.delete(f"/Groups/{created['id']}", scim_token)
    assert resp.status_code == 204

    # User should still be active and retrievable
    user_resp = ScimClient.get(f"/Users/{user['id']}", scim_token)
    assert user_resp.status_code == 200
    assert user_resp.json()["active"] is True


# ------------------------------------------------------------------
# Error cases
# ------------------------------------------------------------------


def test_create_group_duplicate_name(scim_token: str, idp_style: str) -> None:
    """POST /Groups with an already-taken displayName returns 409."""
    name = f"Dup Name Group {idp_style}"
    resp1 = _create_scim_group(scim_token, name, external_id="ext-dup-g1")
    assert resp1.status_code == 201

    resp2 = _create_scim_group(scim_token, name, external_id="ext-dup-g2")
    assert resp2.status_code == 409


def test_get_nonexistent_group(scim_token: str) -> None:
    """GET /Groups/{bad-id} returns 404."""
    resp = ScimClient.get("/Groups/999999999", scim_token)
    assert resp.status_code == 404


def test_create_group_with_invalid_member(scim_token: str) -> None:
    """POST /Groups with a non-existent member UUID returns 400."""
    resp = _create_scim_group(
        scim_token,
        "Bad Member Group",
        external_id="ext-bad-m",
        members=[{"value": "00000000-0000-0000-0000-000000000000"}],
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_patch_add_nonexistent_member(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} adding a non-existent member returns 400."""
    created = _create_scim_group(
        scim_token,
        f"Patch Bad Member Group {idp_style}",
        external_id="ext-pbm",
    ).json()

    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [
                {
                    "op": "add",
                    "path": "members",
                    "value": [{"value": "00000000-0000-0000-0000-000000000000"}],
                }
            ],
            idp_style,
        ),
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_patch_add_duplicate_member_is_idempotent(
    scim_token: str, idp_style: str
) -> None:
    """PATCH /Groups/{id} adding an already-present member succeeds silently."""
    user = _create_scim_user(
        scim_token, f"grp_dup_add_{idp_style}@example.com", "ext-gda-1"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Idempotent Add Group {idp_style}",
        external_id="ext-idem-g",
        members=[{"value": user["id"]}],
    ).json()
    assert len(created["members"]) == 1

    # Add same member again
    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "add", "path": "members", "value": [{"value": user["id"]}]}],
            idp_style,
        ),
    )
    assert resp.status_code == 200
    assert len(resp.json()["members"]) == 1  # still just one member
