"""Group/public access control for MCP servers, exercised at the DB layer.

These verify the read path (`get_mcp_servers_accessible_to_user` /
`user_can_access_mcp_server`) directly against Postgres rows, so they don't
depend on the EE group-write path. Access rows are inserted by hand."""

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


def _make_server(db_session: Session, name: str, is_public: bool) -> MCPServer:
    server = MCPServer(
        owner="admin@example.com",
        name=f"{name}",
        server_url="https://example.com/mcp",
        is_public=is_public,
    )
    db_session.add(server)
    db_session.commit()
    db_session.refresh(server)
    return server


def _make_group(db_session: Session, name: str) -> UserGroup:
    group = UserGroup(name=f"{name}_{uuid4().hex[:8]}", is_up_to_date=True)
    db_session.add(group)
    db_session.commit()
    db_session.refresh(group)
    return group


def _add_user_to_group(db_session: Session, user: User, group: UserGroup) -> None:
    db_session.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
    db_session.commit()


def _restrict_to_group(
    db_session: Session, server: MCPServer, group: UserGroup
) -> None:
    db_session.add(
        MCPServer__UserGroup(mcp_server_id=server.id, user_group_id=group.id)
    )
    db_session.commit()


def _restrict_to_user(db_session: Session, server: MCPServer, user: User) -> None:
    db_session.add(MCPServer__User(mcp_server_id=server.id, user_id=user.id))
    db_session.commit()


def _accessible_ids(user: User, db_session: Session) -> set[int]:
    return {s.id for s in get_mcp_servers_accessible_to_user(user, db_session)}


def test_public_server_visible_to_every_user(db_session: Session) -> None:
    user = create_test_user(db_session, "mcp_pub", role=UserRole.BASIC)
    public = _make_server(db_session, "mcp_pub_server", is_public=True)

    assert public.id in _accessible_ids(user, db_session)
    assert user_can_access_mcp_server(user, public.id, db_session) is True


def test_group_restricted_server_gates_by_membership(db_session: Session) -> None:
    member = create_test_user(db_session, "mcp_member", role=UserRole.BASIC)
    outsider = create_test_user(db_session, "mcp_outsider", role=UserRole.BASIC)
    group = _make_group(db_session, "mcp_group")
    _add_user_to_group(db_session, member, group)

    restricted = _make_server(db_session, "mcp_group_server", is_public=False)
    _restrict_to_group(db_session, restricted, group)

    assert restricted.id in _accessible_ids(member, db_session)
    assert user_can_access_mcp_server(member, restricted.id, db_session) is True

    assert restricted.id not in _accessible_ids(outsider, db_session)
    assert user_can_access_mcp_server(outsider, restricted.id, db_session) is False


def test_user_restricted_server_gates_by_direct_grant(db_session: Session) -> None:
    granted = create_test_user(db_session, "mcp_granted", role=UserRole.BASIC)
    other = create_test_user(db_session, "mcp_other", role=UserRole.BASIC)

    restricted = _make_server(db_session, "mcp_user_server", is_public=False)
    _restrict_to_user(db_session, restricted, granted)

    assert user_can_access_mcp_server(granted, restricted.id, db_session) is True
    assert user_can_access_mcp_server(other, restricted.id, db_session) is False


def test_admin_sees_all_servers(db_session: Session) -> None:
    admin = create_test_user(db_session, "mcp_admin", role=UserRole.ADMIN)
    restricted = _make_server(db_session, "mcp_admin_restricted", is_public=False)

    assert restricted.id in _accessible_ids(admin, db_session)
    assert user_can_access_mcp_server(admin, restricted.id, db_session) is True


def test_non_member_cannot_access_other_groups_server(db_session: Session) -> None:
    user = create_test_user(db_session, "mcp_wronggroup", role=UserRole.BASIC)
    user_group = _make_group(db_session, "mcp_users_group")
    _add_user_to_group(db_session, user, user_group)

    other_group = _make_group(db_session, "mcp_restricted_group")
    restricted = _make_server(db_session, "mcp_othergroup_server", is_public=False)
    _restrict_to_group(db_session, restricted, other_group)

    assert restricted.id not in _accessible_ids(user, db_session)
    assert user_can_access_mcp_server(user, restricted.id, db_session) is False
