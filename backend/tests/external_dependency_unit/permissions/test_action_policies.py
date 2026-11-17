"""Permission ownership, full-scope saves, and live enforcement on PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.action_policy import (
    get_gated_app_id,
    get_or_create_gated_app_id,
    get_workspace_action_policies,
    list_action_policies,
    replace_workspace_action_policies,
    save_user_action_policies,
)
from onyx.db.enums import (
    ActionPolicy,
    ExternalAppType,
    GatedAppKind,
    ScheduledTaskRunStatus,
    ScheduledTaskTriggerSource,
    SessionOrigin,
)
from onyx.db.mcp import (
    create_mcp_server__no_commit,
)
from onyx.db.models import (
    BuildSession,
    ExternalApp,
    GatedApp,
    ScheduledTaskRun,
    Tool,
    User,
)
from onyx.db.scheduled_task import (
    create_scheduled_task,
    get_active_scheduled_task_context,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import (
    AppActionPolicies,
    SaveActionPolicies,
)
from onyx.server.features.action_policies import api

ASK = ActionPolicy.ASK
ALLOW = ActionPolicy.ALWAYS
DENY = ActionPolicy.DENY
READ = "slack.messages.read"
WRITE = "slack.messages.write"


@pytest.fixture
def owner_and_app(db_session: Session) -> tuple[User, int]:
    user = User(
        id=uuid4(),
        email=f"permissions-{uuid4()}@example.com",
        hashed_password="unused",
        is_active=True,
        is_verified=True,
    )
    app = ExternalApp(
        name="Permission test",
        app_type=ExternalAppType.SLACK,
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    )
    db_session.add_all([user, app])
    db_session.flush()
    return user, get_or_create_gated_app_id(
        db_session, GatedAppKind.EXTERNAL_APP, app.id
    )


def _settings(app_id: int, policies: dict[str, ActionPolicy]) -> AppActionPolicies:
    return AppActionPolicies(gated_app_id=app_id, action_policies=policies)


def test_personal_mcp_settings_require_server_access(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    owner, _ = owner_and_app
    outsider = User(
        id=uuid4(),
        email=f"permissions-outsider-{uuid4()}@example.com",
        hashed_password="unused",
        is_active=True,
        is_verified=True,
    )
    db_session.add(outsider)
    server = create_mcp_server__no_commit(
        owner_email=owner.email,
        name="Private MCP",
        description=None,
        server_url="https://example.com/private-mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
        is_public=False,
    )
    db_session.add(
        Tool(name="send_report", description="Send report", mcp_server_id=server.id)
    )
    db_session.flush()
    app_id = get_or_create_gated_app_id(db_session, GatedAppKind.MCP_SERVER, server.id)

    with pytest.raises(OnyxError, match="App is unavailable"):
        list_action_policies(
            db_session, outsider, target=(GatedAppKind.MCP_SERVER, server.id)
        )
    with pytest.raises(OnyxError, match="App is unavailable"):
        save_user_action_policies(
            db_session, outsider, _settings(app_id, {"send_report": ALLOW})
        )
    save_user_action_policies(
        db_session, owner, _settings(app_id, {"send_report": ALLOW})
    )

    replace_workspace_action_policies(db_session, app_id, None, users_can_manage=False)
    with pytest.raises(OnyxError, match="Workspace settings prevent"):
        save_user_action_policies(
            db_session, owner, _settings(app_id, {"send_report": ASK})
        )


def test_active_run_keeps_task_context_until_completion(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, _ = owner_and_app
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Daily",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        plugins=[],
    )
    session = BuildSession(user_id=user.id)
    db_session.add(session)
    db_session.flush()
    run = ScheduledTaskRun(
        task_id=task.id,
        session_id=session.id,
        status=ScheduledTaskRunStatus.RUNNING,
        trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
    )
    db_session.add(run)
    db_session.flush()
    task.deleted = True
    db_session.flush()
    assert get_active_scheduled_task_context(db_session, session.id) == (
        run.id,
        task.id,
    )
    for status in ScheduledTaskRunStatus:
        if status == ScheduledTaskRunStatus.RUNNING:
            continue
        run.status = status
        db_session.flush()
        with pytest.raises(OnyxError, match="Scheduled execution is no longer active"):
            get_active_scheduled_task_context(db_session, session.id)


def test_single_app_save_does_not_create_unrelated_app_identities(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, app_id = owner_and_app
    unrelated = ExternalApp(
        name="Unrelated",
        app_type=ExternalAppType.SLACK,
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    )
    db_session.add(unrelated)
    db_session.flush()
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ALLOW}))
    assert (
        list_action_policies(db_session, user, gated_app_id=app_id)[0].gated_app_id
        == app_id
    )
    assert get_gated_app_id(db_session, GatedAppKind.EXTERNAL_APP, unrelated.id) is None


def test_workspace_save_uses_catalog_inheritance(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, app_id = owner_and_app
    app = db_session.get(GatedApp, app_id)
    assert app is not None and app.external_app_id is not None
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: ASK, READ: ALLOW}, users_can_manage=True
    )
    assert (
        get_workspace_action_policies(
            db_session, GatedAppKind.EXTERNAL_APP, app.external_app_id
        )
        == {}
    )
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: ALLOW, READ: ASK}, users_can_manage=None
    )
    assert get_workspace_action_policies(
        db_session, GatedAppKind.EXTERNAL_APP, app.external_app_id
    ) == {WRITE: ALLOW, READ: ASK}


def test_scheduled_session_without_active_run_cannot_use_personal_policies(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, _ = owner_and_app
    session = BuildSession(user_id=user.id, origin=SessionOrigin.SCHEDULED)
    db_session.add(session)
    db_session.flush()
    with pytest.raises(OnyxError, match="Scheduled execution is no longer active"):
        get_active_scheduled_task_context(db_session, session.id)
    session.origin = SessionOrigin.INTERACTIVE
    db_session.flush()
    assert get_active_scheduled_task_context(db_session, session.id) is None


def test_personal_routes_require_craft_only_for_external_apps(
    db_session: Session,
    owner_and_app: tuple[User, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    user, external_app_id = owner_and_app
    monkeypatch.setattr(api, "is_craft_enabled_for_user", lambda _user: False)
    server = create_mcp_server__no_commit(
        owner_email=user.email,
        name="Chat MCP",
        description=None,
        server_url="https://example.com/chat-mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
        is_public=True,
    )
    db_session.add(
        Tool(name="send_report", description="Send report", mcp_server_id=server.id)
    )
    db_session.flush()
    get_or_create_gated_app_id(db_session, GatedAppKind.MCP_SERVER, server.id)

    saved = api.save_personal_action_policies(
        "mcp_server",
        server.id,
        SaveActionPolicies(action_policies={"send_report": ALLOW}),
        user,
        db_session,
    )
    assert saved.actions[0].effective_policy == ALLOW
    assert (
        api.get_personal_action_policies("mcp_server", server.id, user, db_session)
        .actions[0]
        .stored_policy
        == ALLOW
    )
    external_target = list_action_policies(
        db_session, user, gated_app_id=external_app_id
    )[0].target_id
    with pytest.raises(OnyxError, match="Onyx Craft is not available"):
        api.get_personal_action_policies(
            "external_app", external_target, user, db_session
        )
    with pytest.raises(OnyxError, match="Onyx Craft is not available"):
        api.save_personal_action_policies(
            "external_app",
            external_target,
            SaveActionPolicies(action_policies={READ: ALLOW}),
            user,
            db_session,
        )
