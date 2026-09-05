"""Owner scoping on routes BASIC_ACCESS admits everyone to.

The gate proves nothing here — only a per-handler owner filter separates two
users' data. The access matrix probes these paths with bogus ids and asserts
only that the gate admitted the caller, so a missing filter fails nothing.
"""

import os

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.permission_state import effective_permissions
from tests.integration.common_utils.test_models import DATestUser

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Custom group permission assignment is enterprise only",
)


# Exhaustive: each handler re-filters on UserProject.user_id independently, so
# one missing filter is a silent cross-user read or delete.
PROJECT_SCOPED_ROUTES: list[tuple[str, str]] = [
    ("GET", "/user/projects/{id}"),
    ("GET", "/user/projects/files/{id}"),
    ("GET", "/user/projects/{id}/details"),
    ("GET", "/user/projects/{id}/instructions"),
    ("GET", "/user/projects/{id}/token-count"),
    ("PATCH", "/user/projects/{id}"),
    ("DELETE", "/user/projects/{id}"),
]

_BODY_BY_ROUTE: dict[str, dict[str, object]] = {
    "PATCH": {"name": "renamed-by-intruder"},
}


# Module-scoped and additive like the rest of this package — no per-test reset.
# permission_admin_user first, so neither principal below is the admin and
# nothing passes via the short-circuit.
@pytest.fixture(scope="module")
def owner(permission_admin_user: DATestUser) -> DATestUser:
    """Holds ADD_AGENTS — EE never grants it by default, so persona creation 403s."""
    user = UserManager.create(name="isolation_owner")
    grant_group = UserGroupManager.create(
        name="isolation-owner-group",
        user_ids=[user.id],
        user_performing_action=permission_admin_user,
    )
    UserGroupManager.set_permissions(
        user_group=grant_group,
        permissions=[Permission.ADD_AGENTS.value],
        user_performing_action=permission_admin_user,
    ).raise_for_status()
    return user


@pytest.fixture(scope="module")
def publisher(permission_admin_user: DATestUser) -> tuple[DATestUser, int]:
    """An owner holding no ADD_AGENTS — the shape e55a92be61 fixed. Creating the agent
    needs the grant and publishing it must not, so the grant is revoked in between."""
    user = UserManager.create(name="isolation_publisher")
    grant_group = UserGroupManager.create(
        name="isolation-publisher-group",
        user_ids=[user.id],
        user_performing_action=permission_admin_user,
    )
    UserGroupManager.set_permissions(
        user_group=grant_group,
        permissions=[Permission.ADD_AGENTS.value],
        user_performing_action=permission_admin_user,
    ).raise_for_status()

    persona = PersonaManager.create(user_performing_action=user, is_public=False)

    UserGroupManager.set_permissions(
        user_group=grant_group,
        permissions=[],
        user_performing_action=permission_admin_user,
    ).raise_for_status()
    return user, persona.id


@pytest.fixture(scope="module")
def intruder(permission_admin_user: DATestUser) -> DATestUser:  # noqa: ARG001
    return UserManager.create(name="isolation_intruder")


@pytest.mark.parametrize("method,path_template", PROJECT_SCOPED_ROUTES)
def test_project_routes_are_owner_scoped(
    method: str,
    path_template: str,
    owner: DATestUser,
    intruder: DATestUser,
) -> None:
    project = ProjectManager.create(
        name="isolation-project", user_performing_action=owner
    )
    path = path_template.format(id=project.id)

    resp = client.request(
        method,
        f"{API_SERVER_URL}{path}",
        headers=intruder.headers,
        cookies=intruder.cookies,
        json=_BODY_BY_ROUTE.get(method),
        timeout=30,
    )

    assert resp.status_code in (403, 404), (
        f"{method} {path} leaked another user's project to a non-owner: "
        f"{resp.status_code} (body={resp.text[:200]})"
    )

    # A handler that 404s everyone would pass the assertion above.
    still_there = client.get(
        f"{API_SERVER_URL}/user/projects/{project.id}",
        headers=owner.headers,
        cookies=owner.cookies,
        timeout=30,
    )
    assert still_there.status_code == 200, still_there.text


@pytest.mark.parametrize("action", ["public", "share"])
def test_persona_write_routes_are_owner_scoped(
    action: str,
    owner: DATestUser,
    intruder: DATestUser,
) -> None:
    """BASIC_ACCESS + GATE 2: the gate admits anyone, update_persona_* enforces
    ownership. The matrix covers only the gate, with id 999999."""
    persona = PersonaManager.create(user_performing_action=owner, is_public=False)

    body: dict[str, object] = (
        {"is_public": True} if action == "public" else {"user_ids": []}
    )
    resp = client.patch(
        f"{API_SERVER_URL}/persona/{persona.id}/{action}",
        headers=intruder.headers,
        cookies=intruder.cookies,
        json=body,
        timeout=30,
    )

    assert resp.status_code in (403, 404), (
        f"a non-owner changed another user's persona via /{action}: "
        f"{resp.status_code} (body={resp.text[:200]})"
    )


def test_persona_owner_can_publish_own_agent(
    publisher: tuple[DATestUser, int],
) -> None:
    """The other half of GATE 2. Requiring ADD_AGENTS here would 403 an owner who
    can already publish the same agent through /share — what e55a92be61 fixed."""
    owner, persona_id = publisher

    # the shared `owner` holds ADD_AGENTS for persona creation, which would make a
    # reintroduced gate pass here; this assert keeps that drift from going unnoticed
    assert Permission.ADD_AGENTS.value not in effective_permissions(owner.id), (
        "publisher must not hold ADD_AGENTS or this proves nothing"
    )

    resp = client.patch(
        f"{API_SERVER_URL}/persona/{persona_id}/public",
        headers=owner.headers,
        cookies=owner.cookies,
        json={"is_public": True},
        timeout=30,
    )
    assert resp.status_code == 200, resp.text
