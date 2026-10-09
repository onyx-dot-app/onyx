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

import httpx
import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import (
    ADMIN_USER_NAME,
    API_SERVER_URL,
    GENERAL_HEADERS,
)
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.scim_client import ScimClient
from tests.integration.common_utils.managers.scim_token import ScimTokenManager
from tests.integration.common_utils.managers.user import (
    DEFAULT_PASSWORD,
    UserManager,
    build_email,
)
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.permission_state import (
    effective_permissions,
    is_group_manager,
    managed_group_ids,
)
from tests.integration.common_utils.test_models import DATestUser

SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
MANAGE_LLMS = Permission.MANAGE_LLMS.value


@pytest.fixture(scope="module", params=["okta", "entra"])
def idp_style(request: pytest.FixtureRequest) -> str:
    """Parameterized IdP style — runs every test with both Okta and Entra request formats."""
    return request.param


@pytest.fixture(scope="module")
def scim_admin() -> DATestUser:
    """The admin that owns the SCIM token, also used to drive the non-SCIM admin
    API. Uses UserManager directly to avoid fixture-scope conflicts with the
    function-scoped admin_user fixture."""
    try:
        return UserManager.create(name=ADMIN_USER_NAME)
    except Exception:
        return UserManager.login_as_user(
            DATestUser(
                id="",
                email=build_email(ADMIN_USER_NAME),
                password=DEFAULT_PASSWORD,
                headers=GENERAL_HEADERS,
                is_admin=True,
                is_active=True,
            )
        )


@pytest.fixture(scope="module")
def scim_token(idp_style: str, scim_admin: DATestUser) -> str:
    """Create a single SCIM token shared across all tests in this module.

    Creating a new token revokes the previous one, so we create exactly once
    per IdP-style run and reuse.
    """
    token = ScimTokenManager.create(
        name=f"scim-group-tests-{idp_style}",
        user_performing_action=scim_admin,
    ).raw_token
    assert token is not None
    return token


def _set_manager(
    group_id: str, user_id: str, is_manager: bool, admin: DATestUser
) -> None:
    """Seed through the real route: a test that plants the edge itself can't
    detect production losing it."""
    UserGroupManager.set_manager_by_id(
        group_id, user_id, is_manager, admin
    ).raise_for_status()


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


def _create_scim_user(token: str, email: str, external_id: str) -> httpx.Response:
    return ScimClient.post(
        "/Users", token, json=_make_user_resource(email, external_id)
    )


def _create_scim_group(
    token: str,
    display_name: str,
    external_id: str | None = None,
    members: list[dict] | None = None,
) -> httpx.Response:
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
    resp = _create_scim_group(scim_token, name, external_id=f"ext-eng-{idp_style}")
    assert resp.status_code == 201

    body = resp.json()
    assert body["displayName"] == name
    assert body["externalId"] == f"ext-eng-{idp_style}"
    assert body["id"]  # integer ID assigned by server
    assert body["meta"]["resourceType"] == "Group"


def test_create_group_with_members(scim_token: str, idp_style: str) -> None:
    """POST /Groups with members populates the member list."""
    user = _create_scim_user(
        scim_token, f"grp_member1_{idp_style}@example.com", f"ext-gm-{idp_style}"
    ).json()

    resp = _create_scim_group(
        scim_token,
        f"Backend Team {idp_style}",
        external_id=f"ext-backend-{idp_style}",
        members=[{"value": user["id"]}],
    )
    assert resp.status_code == 201

    body = resp.json()
    member_ids = [m["value"] for m in body["members"]]
    assert user["id"] in member_ids


def test_get_group(scim_token: str, idp_style: str) -> None:
    """GET /Groups/{id} returns the group resource including members."""
    user = _create_scim_user(
        scim_token, f"grp_get_m_{idp_style}@example.com", f"ext-ggm-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Frontend Team {idp_style}",
        external_id=f"ext-fe-{idp_style}",
        members=[{"value": user["id"]}],
    ).json()

    resp = ScimClient.get(f"/Groups/{created['id']}", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["id"] == created["id"]
    assert body["displayName"] == f"Frontend Team {idp_style}"
    assert body["externalId"] == f"ext-fe-{idp_style}"
    member_ids = [m["value"] for m in body["members"]]
    assert user["id"] in member_ids


def test_list_groups(scim_token: str, idp_style: str) -> None:
    """GET /Groups returns a ListResponse containing provisioned groups."""
    name = f"DevOps Team {idp_style}"
    _create_scim_group(scim_token, name, external_id=f"ext-devops-{idp_style}")

    resp = ScimClient.get("/Groups", scim_token)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totalResults"] >= 1
    names = [r["displayName"] for r in body["Resources"]]
    assert name in names


def test_list_groups_pagination(scim_token: str, idp_style: str) -> None:
    """GET /Groups with startIndex and count returns correct pagination."""
    _create_scim_group(
        scim_token, f"Page Group A {idp_style}", external_id=f"ext-page-a-{idp_style}"
    )
    _create_scim_group(
        scim_token, f"Page Group B {idp_style}", external_id=f"ext-page-b-{idp_style}"
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
    _create_scim_group(scim_token, name, external_id=f"ext-qa-filter-{idp_style}")

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
        scim_token,
        f"Original Name {idp_style}",
        external_id=f"ext-replace-g-{idp_style}",
    ).json()

    user = _create_scim_user(
        scim_token, f"grp_replace_m_{idp_style}@example.com", f"ext-grm-{idp_style}"
    ).json()

    updated_resource = _make_group_resource(
        display_name=f"Renamed Group {idp_style}",
        external_id=f"ext-replace-g-{idp_style}",
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
        scim_token, f"grp_clear_m_{idp_style}@example.com", f"ext-gcm-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Clear Members Group {idp_style}",
        external_id=f"ext-clear-g-{idp_style}",
        members=[{"value": user["id"]}],
    ).json()

    assert len(created["members"]) == 1

    resp = ScimClient.put(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_group_resource(
            f"Clear Members Group {idp_style}", f"ext-clear-g-{idp_style}", members=[]
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["members"] == []


def test_replace_group_preserves_manager_for_retained_member(
    scim_token: str, idp_style: str, scim_admin: DATestUser
) -> None:
    """IdPs push PUT /Groups on routine reconciliation, so a
    delete-all-then-reinsert replace would strip every manager on each sync —
    silently, since the new row takes is_manager's server_default."""
    keeper = _create_scim_user(
        scim_token, f"grp_mgr_keep_{idp_style}@example.com", f"ext-gmk-{idp_style}"
    ).json()
    dropped = _create_scim_user(
        scim_token, f"grp_mgr_drop_{idp_style}@example.com", f"ext-gmd-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Manager Sync Group {idp_style}",
        external_id=f"ext-mgr-sync-{idp_style}",
        members=[{"value": keeper["id"]}, {"value": dropped["id"]}],
    ).json()

    _set_manager(created["id"], keeper["id"], True, scim_admin)
    _set_manager(created["id"], dropped["id"], True, scim_admin)
    assert UserGroupManager.get_manager_ids(created["id"], scim_admin) == {
        keeper["id"],
        dropped["id"],
    }

    resp = ScimClient.put(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_group_resource(
            f"Manager Sync Group {idp_style}",
            f"ext-mgr-sync-{idp_style}",
            members=[{"value": keeper["id"]}],
        ),
    )
    assert resp.status_code == 200

    # keeper stays a manager; dropped loses it only because they left the group.
    assert UserGroupManager.get_manager_ids(created["id"], scim_admin) == {keeper["id"]}

    # get_manager_ids reads edge rows, which the removal deletes regardless of whether the
    # rollup recompute ran. Assert the cached is_group_manager column (what GATE 1 reads) and
    # the source edges agree: cleared for the departed manager, intact for the keeper.
    assert is_group_manager(dropped["id"]) is False
    assert managed_group_ids(dropped["id"]) == set()
    assert is_group_manager(keeper["id"]) is True
    assert managed_group_ids(keeper["id"]) == {int(created["id"])}


def test_patch_group_preserves_manager_for_retained_member(
    scim_token: str, idp_style: str, scim_admin: DATestUser
) -> None:
    """PATCH diffs rather than replacing, so an unrelated add must not disturb an
    existing manager. Pins PUT and PATCH to the same contract."""
    manager = _create_scim_user(
        scim_token, f"grp_mgr_patch_{idp_style}@example.com", f"ext-gmp-{idp_style}"
    ).json()
    newcomer = _create_scim_user(
        scim_token, f"grp_mgr_new_{idp_style}@example.com", f"ext-gmn-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Manager Patch Group {idp_style}",
        external_id=f"ext-mgr-patch-{idp_style}",
        members=[{"value": manager["id"]}],
    ).json()

    _set_manager(created["id"], manager["id"], True, scim_admin)

    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "add", "path": "members", "value": [{"value": newcomer["id"]}]}],
            idp_style,
        ),
    )
    assert resp.status_code == 200

    assert UserGroupManager.get_manager_ids(created["id"], scim_admin) == {
        manager["id"]
    }


def test_patch_add_member(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} with op=add adds a member."""
    created = _create_scim_group(
        scim_token,
        f"Patch Add Group {idp_style}",
        external_id=f"ext-patch-add-{idp_style}",
    ).json()
    user = _create_scim_user(
        scim_token, f"grp_patch_add_{idp_style}@example.com", f"ext-gpa-{idp_style}"
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
        scim_token, f"grp_patch_rm_{idp_style}@example.com", f"ext-gpr-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Patch Remove Group {idp_style}",
        external_id=f"ext-patch-rm-{idp_style}",
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
        scim_token, f"grp_repl_a_{idp_style}@example.com", f"ext-gra-{idp_style}"
    ).json()
    user_b = _create_scim_user(
        scim_token, f"grp_repl_b_{idp_style}@example.com", f"ext-grb-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Patch Replace Group {idp_style}",
        external_id=f"ext-patch-repl-{idp_style}",
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
        external_id=f"ext-rename-g-{idp_style}",
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
        external_id=f"ext-del-g-{idp_style}",
    ).json()

    resp = ScimClient.delete(f"/Groups/{created['id']}", scim_token)
    assert resp.status_code == 204

    # Second DELETE returns 404 (group hard-deleted)
    resp2 = ScimClient.delete(f"/Groups/{created['id']}", scim_token)
    assert resp2.status_code == 404


def test_delete_group_preserves_members(scim_token: str, idp_style: str) -> None:
    """DELETE /Groups/{id} removes memberships but does not deactivate users."""
    user = _create_scim_user(
        scim_token, f"grp_del_member_{idp_style}@example.com", f"ext-gdm-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Delete With Members {idp_style}",
        external_id=f"ext-del-wm-{idp_style}",
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
    resp1 = _create_scim_group(scim_token, name, external_id=f"ext-dup-g1-{idp_style}")
    assert resp1.status_code == 201

    resp2 = _create_scim_group(scim_token, name, external_id=f"ext-dup-g2-{idp_style}")
    assert resp2.status_code == 409


def test_get_nonexistent_group(scim_token: str) -> None:
    """GET /Groups/{bad-id} returns 404."""
    resp = ScimClient.get("/Groups/999999999", scim_token)
    assert resp.status_code == 404


def test_create_group_with_invalid_member(scim_token: str, idp_style: str) -> None:
    """POST /Groups with a non-existent member UUID returns 400."""
    resp = _create_scim_group(
        scim_token,
        f"Bad Member Group {idp_style}",
        external_id=f"ext-bad-m-{idp_style}",
        members=[{"value": "00000000-0000-0000-0000-000000000000"}],
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_patch_add_nonexistent_member(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} adding a non-existent member returns 400."""
    created = _create_scim_group(
        scim_token,
        f"Patch Bad Member Group {idp_style}",
        external_id=f"ext-pbm-{idp_style}",
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
        scim_token, f"grp_dup_add_{idp_style}@example.com", f"ext-gda-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Idempotent Add Group {idp_style}",
        external_id=f"ext-idem-g-{idp_style}",
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


def test_create_group_reserved_name_admin(scim_token: str) -> None:
    """POST /Groups with reserved name 'Admin' returns 409."""
    resp = _create_scim_group(scim_token, "Admin", external_id="ext-reserved-admin")
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_create_group_reserved_name_basic(scim_token: str) -> None:
    """POST /Groups with reserved name 'Basic' returns 409."""
    resp = _create_scim_group(scim_token, "Basic", external_id="ext-reserved-basic")
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_replace_group_cannot_rename_to_reserved(
    scim_token: str, idp_style: str
) -> None:
    """PUT /Groups/{id} renaming a group to 'Admin' returns 409."""
    created = _create_scim_group(
        scim_token,
        f"Rename To Reserved {idp_style}",
        external_id=f"ext-rtr-{idp_style}",
    ).json()

    resp = ScimClient.put(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_group_resource(
            display_name="Admin", external_id=f"ext-rtr-{idp_style}"
        ),
    )
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_patch_rename_to_reserved_name(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} renaming a group to 'Basic' returns 409."""
    created = _create_scim_group(
        scim_token,
        f"Patch Rename Reserved {idp_style}",
        external_id=f"ext-prr-{idp_style}",
    ).json()

    resp = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "displayName", "value": "Basic"}],
            idp_style,
        ),
    )
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_delete_reserved_group_rejected(scim_token: str) -> None:
    """DELETE /Groups/{id} on a reserved group ('Admin') returns 409."""
    # Look up the reserved 'Admin' group via SCIM filter
    resp = ScimClient.get('/Groups?filter=displayName eq "Admin"', scim_token)
    assert resp.status_code == 200
    resources = resp.json()["Resources"]
    assert len(resources) >= 1, "Expected reserved 'Admin' group to exist"
    admin_group_id = resources[0]["id"]

    resp = ScimClient.delete(f"/Groups/{admin_group_id}", scim_token)
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_scim_created_group_has_basic_permission(
    scim_token: str, idp_style: str
) -> None:
    """POST /Groups assigns the 'basic' permission to the group itself."""
    # Create a SCIM group (no members needed — we check the group's permissions)
    resp = _create_scim_group(
        scim_token,
        f"Basic Perm Group {idp_style}",
        external_id=f"ext-basic-perm-{idp_style}",
    )
    assert resp.status_code == 201
    group_id = resp.json()["id"]

    # Log in as the admin user (created by the scim_token fixture).
    admin = DATestUser(
        id="",
        email=build_email(ADMIN_USER_NAME),
        password=DEFAULT_PASSWORD,
        headers=GENERAL_HEADERS,
        is_admin=True,
        is_active=True,
    )
    admin = UserManager.login_as_user(admin)

    # Verify the group itself was granted the basic permission. BASIC_ACCESS
    # is non-toggleable so the default GET response hides it; pass
    # include_non_toggleable=true to surface all grants for this assertion.
    perms_resp = client.get(
        f"{API_SERVER_URL}/manage/admin/user-group/{group_id}/permissions",
        params={"include_non_toggleable": "true"},
        headers=admin.headers,
    )
    perms_resp.raise_for_status()
    perms = perms_resp.json()
    assert "basic" in perms, f"SCIM group should have 'basic' permission, got: {perms}"


def test_replace_group_cannot_rename_from_reserved(scim_token: str) -> None:
    """PUT /Groups/{id} renaming a reserved group ('Admin') to a non-reserved name returns 409."""
    resp = ScimClient.get('/Groups?filter=displayName eq "Admin"', scim_token)
    assert resp.status_code == 200
    resources = resp.json()["Resources"]
    assert len(resources) >= 1, "Expected reserved 'Admin' group to exist"
    admin_group_id = resources[0]["id"]

    resp = ScimClient.put(
        f"/Groups/{admin_group_id}",
        scim_token,
        json=_make_group_resource(
            display_name="RenamedAdmin", external_id="ext-rename-from-reserved"
        ),
    )
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_patch_rename_from_reserved_name(scim_token: str, idp_style: str) -> None:
    """PATCH /Groups/{id} renaming a reserved group ('Admin') returns 409."""
    resp = ScimClient.get('/Groups?filter=displayName eq "Admin"', scim_token)
    assert resp.status_code == 200
    resources = resp.json()["Resources"]
    assert len(resources) >= 1, "Expected reserved 'Admin' group to exist"
    admin_group_id = resources[0]["id"]

    resp = ScimClient.patch(
        f"/Groups/{admin_group_id}",
        scim_token,
        json=_make_patch_request(
            [{"op": "replace", "path": "displayName", "value": "RenamedAdmin"}],
            idp_style,
        ),
    )
    assert resp.status_code == 409
    assert "reserved" in resp.json()["detail"].lower()


def test_scim_group_create_propagates_permissions(
    scim_token: str, idp_style: str, scim_admin: DATestUser
) -> None:
    user = _create_scim_user(
        scim_token, f"scim_prop_create_{idp_style}@example.com", f"ext-spc-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Prop Create Group {idp_style}",
        external_id=f"ext-prop-create-{idp_style}",
        members=[{"value": user["id"]}],
    ).json()

    UserGroupManager.set_permissions_by_id(
        created["id"], [MANAGE_LLMS], scim_admin
    ).raise_for_status()

    assert MANAGE_LLMS in effective_permissions(user["id"])


def test_scim_patch_membership_propagates_permissions(
    scim_token: str, idp_style: str, scim_admin: DATestUser
) -> None:
    user = _create_scim_user(
        scim_token, f"scim_prop_patch_{idp_style}@example.com", f"ext-spp-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Prop Patch Group {idp_style}",
        external_id=f"ext-prop-patch-{idp_style}",
    ).json()
    UserGroupManager.set_permissions_by_id(
        created["id"], [MANAGE_LLMS], scim_admin
    ).raise_for_status()
    assert MANAGE_LLMS not in effective_permissions(user["id"])

    add = ScimClient.patch(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_patch_request(
            [{"op": "add", "path": "members", "value": [{"value": user["id"]}]}],
            idp_style,
        ),
    )
    assert add.status_code == 200
    assert MANAGE_LLMS in effective_permissions(user["id"])

    remove = ScimClient.patch(
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
    assert remove.status_code == 200
    assert MANAGE_LLMS not in effective_permissions(user["id"])


def test_scim_replace_membership_propagates_permissions(
    scim_token: str, idp_style: str, scim_admin: DATestUser
) -> None:
    """PUT recomputes survivors as a batch and departures separately; the two
    calls must agree, so assert both directions."""
    keeper = _create_scim_user(
        scim_token, f"scim_prop_keep_{idp_style}@example.com", f"ext-spk-{idp_style}"
    ).json()
    dropped = _create_scim_user(
        scim_token, f"scim_prop_drop_{idp_style}@example.com", f"ext-spd-{idp_style}"
    ).json()
    added = _create_scim_user(
        scim_token, f"scim_prop_add_{idp_style}@example.com", f"ext-spa-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Prop Replace Group {idp_style}",
        external_id=f"ext-prop-replace-{idp_style}",
        members=[{"value": keeper["id"]}, {"value": dropped["id"]}],
    ).json()
    UserGroupManager.set_permissions_by_id(
        created["id"], [MANAGE_LLMS], scim_admin
    ).raise_for_status()
    assert MANAGE_LLMS in effective_permissions(dropped["id"])

    resp = ScimClient.put(
        f"/Groups/{created['id']}",
        scim_token,
        json=_make_group_resource(
            f"Prop Replace Group {idp_style}",
            f"ext-prop-replace-{idp_style}",
            members=[{"value": keeper["id"]}, {"value": added["id"]}],
        ),
    )
    assert resp.status_code == 200

    assert MANAGE_LLMS in effective_permissions(keeper["id"])
    assert MANAGE_LLMS in effective_permissions(added["id"])
    assert MANAGE_LLMS not in effective_permissions(dropped["id"])


def test_scim_group_delete_revokes_permissions(
    scim_token: str, idp_style: str, scim_admin: DATestUser
) -> None:
    user = _create_scim_user(
        scim_token, f"scim_prop_del_{idp_style}@example.com", f"ext-spdel-{idp_style}"
    ).json()
    created = _create_scim_group(
        scim_token,
        f"Prop Delete Group {idp_style}",
        external_id=f"ext-prop-delete-{idp_style}",
        members=[{"value": user["id"]}],
    ).json()
    UserGroupManager.set_permissions_by_id(
        created["id"], [MANAGE_LLMS], scim_admin
    ).raise_for_status()
    assert MANAGE_LLMS in effective_permissions(user["id"])

    resp = ScimClient.delete(f"/Groups/{created['id']}", scim_token)
    assert resp.status_code == 204

    assert MANAGE_LLMS not in effective_permissions(user["id"])
