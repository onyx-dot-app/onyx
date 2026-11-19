"""The integrations of a scheduled task: the write checks the access of the
owner and the action keys, and the read gives the stored settings."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy
from onyx.db.models import Integration, ScheduledTask, User
from onyx.db.scheduled_task import create_scheduled_task, update_scheduled_task
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.craft import (
    list_task_integration_views,
    load_task_integrations,
)
from onyx.integrations.models import ActionSettings, LinkValue
from onyx.tools.models import IntegrationLinkConfiguration
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("task_integrations_owner")


@pytest.fixture
def created(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    owner: User,
) -> Generator[list[int], None, None]:
    integration_ids: list[int] = []
    try:
        yield integration_ids
    finally:
        db_session.rollback()
        db_session.execute(
            delete(ScheduledTask).where(ScheduledTask.user_id == owner.id)
        )
        db_session.commit()
        delete_integrations(db_session, integration_ids)


def _mcp(db_session: Session, created: list[int], *, published: bool) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
        name=f"task-mcp-{uuid4().hex[:8]}",
        tools=("search", "send_report"),
    )
    created.append(integration.id)
    give_access(
        db_session,
        [integration],
        published=published,
        installation_policy=PluginInstallationPolicy.DEFAULT,
    )
    return integration


def _link(
    integration: Integration, actions: dict[str, LinkValue]
) -> IntegrationLinkConfiguration:
    return IntegrationLinkConfiguration(
        integration_id=integration.id, action_settings=ActionSettings(actions=actions)
    )


def _create(
    db_session: Session, owner: User, links: list[IntegrationLinkConfiguration]
) -> UUID:
    task = create_scheduled_task(
        db_session=db_session,
        user_id=owner.id,
        name="Report",
        prompt="Create a report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        integrations=links,
    )
    db_session.commit()
    return task.id


def test_a_task_stores_and_replaces_its_integrations(
    db_session: Session, created: list[int], owner: User
) -> None:
    first = _mcp(db_session, created, published=True)
    second = _mcp(db_session, created, published=True)
    allow = {"send_report": LinkValue.ALLOW}
    task_id = _create(db_session, owner, [_link(first, allow)])

    views = {
        view.id: view
        for view in list_task_integration_views(db_session, owner, task_id)
    }
    assert views[first.id].enabled is True
    assert views[first.id].action_settings == ActionSettings(actions=allow)
    # The catalog also has each integration that is on for the owner.
    assert views[second.id].enabled is False
    assert views[second.id].action_settings is None
    task = load_task_integrations(db_session, task_id, owner.id)
    assert task.link_settings(first.id) == ActionSettings(actions=allow)
    assert task.link_settings(second.id) is None

    update_scheduled_task(
        db_session=db_session,
        task_id=task_id,
        user_id=owner.id,
        integrations=[_link(second, {})],
    )
    db_session.commit()
    task = load_task_integrations(db_session, task_id, owner.id)
    assert task.link_settings(first.id) is None
    assert task.link_settings(second.id) == ActionSettings()


def test_a_task_refuses_an_integration_with_no_access_and_an_unknown_action(
    db_session: Session, created: list[int], owner: User
) -> None:
    usable = _mcp(db_session, created, published=True)
    private = _mcp(db_session, created, published=False)

    for links, status in (
        ([_link(private, {})], 404),
        ([_link(usable, {"not_an_action": LinkValue.ALLOW})], 400),
        ([_link(usable, {}), _link(usable, {})], 400),
    ):
        with pytest.raises(OnyxError) as error:
            _create(db_session, owner, links)
        assert error.value.status_code == status
        db_session.rollback()


def test_a_task_loses_an_integration_when_its_owner_loses_access(
    db_session: Session, created: list[int], owner: User
) -> None:
    integration = _mcp(db_session, created, published=True)
    task_id = _create(db_session, owner, [_link(integration, {})])
    assert load_task_integrations(db_session, task_id, owner.id).integrations() == [
        integration
    ]

    integration.installation_policy = PluginInstallationPolicy.NOT_AVAILABLE
    db_session.commit()

    task = load_task_integrations(db_session, task_id, owner.id)
    assert task.integrations() == []
    assert task.link_settings(integration.id) is None
