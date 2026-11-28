"""An API app with only an ``api_app`` row is a GraphQL app: each list shows
it next to the others. An integration with no settings of a known shape (one
that a later release wrote) is left out of a list, so the list still works."""

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
from onyx.integrations.service import (
    _shapes,
    admin_detail,
    agent_catalog,
    list_admin_integrations,
    list_member_integrations,
)
from onyx.server.features.integrations.models import (
    IntegrationShape,
    MemberIntegrationState,
)
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
    openapi: Integration
    openapi_grouped: Integration
    graphql: Integration
    graphql_grouped: Integration


@pytest.fixture
def rows(db_session: Session, make_test_user: MakeTestUser, group: UserGroup) -> _Rows:
    """Two openapi and two graphql integrations. Each user has access to
    one of each; the others are limited to a group that no user is in."""
    openapi, _ = make_openapi_integration(db_session, openapi_schema=OPENAPI_SPEC)
    openapi_grouped, _ = make_openapi_integration(
        db_session, openapi_schema=OPENAPI_SPEC
    )
    graphql = _graphql_integration(db_session)
    graphql_grouped = _graphql_integration(db_session)
    give_access(db_session, [openapi, graphql])
    for integration in (openapi_grouped, graphql_grouped):
        _limit_to_group(db_session, integration, group)
    return _Rows(
        admin=make_test_user("skip-shape-admin", is_admin=True),
        member=make_test_user("skip-shape-member"),
        openapi=openapi,
        openapi_grouped=openapi_grouped,
        graphql=graphql,
        graphql_grouped=graphql_grouped,
    )


def test_admin_list_shows_a_graphql_app(db_session: Session, rows: _Rows) -> None:
    ids = {view.id for view in list_admin_integrations(rows.admin, db_session)}
    assert {
        rows.openapi.id,
        rows.openapi_grouped.id,
        rows.graphql.id,
        rows.graphql_grouped.id,
    } <= ids


def test_member_list_shows_a_graphql_app(db_session: Session, rows: _Rows) -> None:
    views = {
        view.id: view for view in list_member_integrations(rows.member, db_session)
    }
    assert views[rows.graphql.id].access.state is not MemberIntegrationState.NO_ACCESS
    assert (
        views[rows.graphql_grouped.id].access.state is MemberIntegrationState.NO_ACCESS
    )
    assert rows.openapi.id in views


def test_agent_catalog_shows_a_graphql_app(db_session: Session, rows: _Rows) -> None:
    ids = {option.id for option in agent_catalog(rows.member, db_session)}
    assert {rows.openapi.id, rows.graphql.id} <= ids


def test_a_direct_read_of_a_graphql_app_has_its_shape(
    db_session: Session, rows: _Rows
) -> None:
    assert admin_detail(rows.admin, rows.graphql, db_session).shape is (
        IntegrationShape.GRAPHQL
    )


def test_a_list_skips_an_integration_of_no_known_shape() -> None:
    unknown = Integration(id=-1, kind=IntegrationKind.API, name="later-release")

    assert _shapes([unknown], {}, skip_unknown=True) == {}
