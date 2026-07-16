"""Edge cases for MCP group/public access, beyond the basic matrix.

All cases insert access rows directly, so they exercise the read path without
the EE write path."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.mcp import get_mcp_servers_accessible_to_user
from onyx.db.mcp import user_can_access_mcp_server
from onyx.db.models import MCPServer
from onyx.db.models import MCPServer__User
from onyx.db.models import MCPServer__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from tests.external_dependency_unit.conftest import create_test_user


def _server(db: Session, name: str, is_public: bool) -> MCPServer:
    s = MCPServer(
        owner="admin@example.com",
        name=name,
        server_url="https://example.com/mcp",
        is_public=is_public,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _group(db: Session, name: str) -> UserGroup:
    g = UserGroup(name=f"{name}_{uuid4().hex[:8]}", is_up_to_date=True)
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _join(db: Session, user: User, group: UserGroup) -> None:
    db.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
    db.commit()


def _restrict_groups(db: Session, server: MCPServer, groups: list[UserGroup]) -> None:
    for g in groups:
        db.add(MCPServer__UserGroup(mcp_server_id=server.id, user_group_id=g.id))
    db.commit()


def _ids(user: User, db: Session) -> set[int]:
    return {s.id for s in get_mcp_servers_accessible_to_user(user, db)}


def test_user_in_multiple_groups_sees_server_via_any_group(db_session: Session) -> None:
    user = create_test_user(db_session, "edge_multi", role=UserRole.BASIC)
    g_a = _group(db_session, "edge_a")
    g_b = _group(db_session, "edge_b")
    _join(db_session, user, g_a)
    _join(db_session, user, g_b)

    # restricted to g_b only; user is in g_a AND g_b -> should see it
    server = _server(db_session, "edge_multi_group_user", is_public=False)
    _restrict_groups(db_session, server, [g_b])

    assert server.id in _ids(user, db_session)
    assert user_can_access_mcp_server(user, server.id, db_session) is True


def test_server_restricted_to_multiple_groups(db_session: Session) -> None:
    member_a = create_test_user(db_session, "edge_ma", role=UserRole.BASIC)
    member_b = create_test_user(db_session, "edge_mb", role=UserRole.BASIC)
    outsider = create_test_user(db_session, "edge_out", role=UserRole.BASIC)
    g_a = _group(db_session, "edge_ga")
    g_b = _group(db_session, "edge_gb")
    _join(db_session, member_a, g_a)
    _join(db_session, member_b, g_b)

    server = _server(db_session, "edge_two_groups", is_public=False)
    _restrict_groups(db_session, server, [g_a, g_b])

    assert user_can_access_mcp_server(member_a, server.id, db_session) is True
    assert user_can_access_mcp_server(member_b, server.id, db_session) is True
    assert user_can_access_mcp_server(outsider, server.id, db_session) is False


def test_private_server_with_no_grants_is_admin_only(db_session: Session) -> None:
    admin = create_test_user(db_session, "edge_admin", role=UserRole.ADMIN)
    basic = create_test_user(db_session, "edge_basic", role=UserRole.BASIC)
    server = _server(db_session, "edge_locked", is_public=False)  # no users, no groups

    assert user_can_access_mcp_server(admin, server.id, db_session) is True
    assert user_can_access_mcp_server(basic, server.id, db_session) is False
    assert server.id not in _ids(basic, db_session)


def test_direct_user_and_group_grants_coexist(db_session: Session) -> None:
    direct = create_test_user(db_session, "edge_direct", role=UserRole.BASIC)
    grp_member = create_test_user(db_session, "edge_grpm", role=UserRole.BASIC)
    group = _group(db_session, "edge_coexist")
    _join(db_session, grp_member, group)

    server = _server(db_session, "edge_mixed", is_public=False)
    db_session.add(MCPServer__User(mcp_server_id=server.id, user_id=direct.id))
    _restrict_groups(db_session, server, [group])

    assert user_can_access_mcp_server(direct, server.id, db_session) is True
    assert user_can_access_mcp_server(grp_member, server.id, db_session) is True


def test_flipping_public_flag_changes_visibility(db_session: Session) -> None:
    outsider = create_test_user(db_session, "edge_flip_out", role=UserRole.BASIC)
    group = _group(db_session, "edge_flip_grp")
    server = _server(db_session, "edge_flip_server", is_public=True)
    _restrict_groups(db_session, server, [group])

    # public flag wins regardless of group rows
    assert user_can_access_mcp_server(outsider, server.id, db_session) is True

    server.is_public = False
    db_session.commit()
    assert user_can_access_mcp_server(outsider, server.id, db_session) is False
