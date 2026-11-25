"""A later release can write an integration that this code cannot read, e.g.
an API app with only an ``api_app`` row. After a rollback, each list skips
that integration and still shows the others."""

from collections.abc import Generator
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ApiAppType,
    IntegrationAuthMode,
    IntegrationKind,
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    ApiApp,
    Integration,
    Integration__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.service import (
    admin_detail,
    agent_catalog,
    list_admin_integrations,
    list_member_integrations,
)
from onyx.server.features.integrations.models import MemberIntegrationState
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.integration_helpers import (
    give_access,
    make_openapi_integration,
)

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Weather", "description": "Weather", "version": "1.0"},
    "servers": [{"url": "https://weather.example.com"}],
    "paths": {
        "/forecast": {"get": {"operationId": "get_forecast", "summary": "Forecast"}}
    },
}


@pytest.fixture
def group(db_session: Session) -> Generator[UserGroup, None, None]:
    """A group with no members, deleted after the test."""
    made = make_group(db_session)
    db_session.commit()
    try:
        yield made
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Integration__UserGroup).where(
                Integration__UserGroup.user_group_id == made.id
            )
        )
        db_session.execute(
            delete(User__UserGroup).where(User__UserGroup.user_group_id == made.id)
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id == made.id))
        db_session.commit()


def _graphql_integration(db_session: Session) -> Integration:
    app = ApiApp(
        api_type=ApiAppType.GRAPHQL,
        base_url="https://graphql.example.com",
        graphql_schema="type Query { hello: String }",
    )
    db_session.add(app)
    db_session.flush()
    integration = Integration(
        kind=IntegrationKind.API,
        name="graphql-from-a-later-release",
        auth_mode=IntegrationAuthMode.NONE,
        api_app_id=app.id,
    )
    db_session.add(integration)
    db_session.commit()
    return integration


def _limit_to_group(
    db_session: Session, integration: Integration, group: UserGroup
) -> None:
    db_session.add(
        Integration__UserGroup(
            integration_id=integration.id,
            user_group_id=group.id,
            permission=SkillSharePermission.VIEWER,
            installation_policy=PluginInstallationPolicy.AVAILABLE,
        )
    )
    db_session.commit()


class _Rows(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    admin: User
    member: User
    readable: Integration
    readable_grouped: Integration
    unreadable: Integration
    unreadable_grouped: Integration


@pytest.fixture
def rows(db_session: Session, make_test_user: MakeTestUser, group: UserGroup) -> _Rows:
    """Two readable and two unreadable integrations. Each user has access to
    one of each; the others are limited to a group that no user is in."""
    readable, _ = make_openapi_integration(db_session, openapi_schema=OPENAPI_SPEC)
    readable_grouped, _ = make_openapi_integration(
        db_session, openapi_schema=OPENAPI_SPEC
    )
    unreadable = _graphql_integration(db_session)
    unreadable_grouped = _graphql_integration(db_session)
    give_access(db_session, [readable, unreadable])
    for integration in (readable_grouped, unreadable_grouped):
        _limit_to_group(db_session, integration, group)
    return _Rows(
        admin=make_test_user("skip-shape-admin", is_admin=True),
        member=make_test_user("skip-shape-member"),
        readable=readable,
        readable_grouped=readable_grouped,
        unreadable=unreadable,
        unreadable_grouped=unreadable_grouped,
    )


def test_admin_list_skips_an_unknown_shape(db_session: Session, rows: _Rows) -> None:
    ids = {view.id for view in list_admin_integrations(rows.admin, db_session)}
    assert {rows.readable.id, rows.readable_grouped.id} <= ids
    assert not {rows.unreadable.id, rows.unreadable_grouped.id} & ids


def test_member_list_skips_an_unknown_shape(db_session: Session, rows: _Rows) -> None:
    views = {
        view.id: view for view in list_member_integrations(rows.member, db_session)
    }
    assert views[rows.readable.id].access.state is not MemberIntegrationState.NO_ACCESS
    assert (
        views[rows.readable_grouped.id].access.state is MemberIntegrationState.NO_ACCESS
    )
    assert not {rows.unreadable.id, rows.unreadable_grouped.id} & set(views)


def test_agent_catalog_skips_an_unknown_shape(db_session: Session, rows: _Rows) -> None:
    ids = {option.id for option in agent_catalog(rows.member, db_session)}
    assert rows.readable.id in ids
    assert rows.unreadable.id not in ids


def test_a_direct_read_of_an_unknown_shape_is_not_found(
    db_session: Session, rows: _Rows
) -> None:
    with pytest.raises(OnyxError) as error:
        admin_detail(rows.admin, rows.unreadable, db_session)
    assert error.value.error_code is OnyxErrorCode.NOT_FOUND
