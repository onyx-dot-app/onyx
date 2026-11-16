"""Permission ownership, full-scope saves, and live enforcement on PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.action_policy import (
    get_active_scheduled_task_context,
    get_gated_app_id,
    get_mcp_tool_default_policies,
    get_or_create_gated_app_id,
    get_task_action_policies,
    get_workspace_action_policies,
    list_action_policies,
    mcp_tool_default_policy,
    replace_workspace_action_policies,
    resolve_action_policies,
    resolve_user_action_policies,
    save_user_action_policies,
    task_app_enabled,
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
    get_craft_enabled_mcp_servers,
    update_mcp_server__no_commit,
    upsert_mcp_server_user_preferences__no_commit,
)
from onyx.db.models import (
    BuildSession,
    ExternalApp,
    GatedApp,
    ScheduledTaskRun,
    Tool,
    User,
    UserActionPolicy,
)
from onyx.db.scheduled_task import create_scheduled_task, update_scheduled_task
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import (
    AppActionPolicies,
    SaveActionPolicies,
    TaskAppActionPolicies,
)
from onyx.server.features.action_policies import api
from onyx.tools.models import ToolConfiguration

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


def _task_settings(
    app_id: int, policies: dict[str, ActionPolicy], *, enabled: bool = True
) -> list[TaskAppActionPolicies]:
    return [
        TaskAppActionPolicies(
            gated_app_id=app_id, enabled=enabled, action_policies=policies
        )
    ]


def test_task_copy_and_personal_settings_are_independent(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    save_user_action_policies(
        db_session, user, _settings(app_id, {WRITE: ALLOW, READ: DENY})
    )
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Daily",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
    )
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {WRITE: ALLOW, READ: DENY}),
    )
    save_user_action_policies(
        db_session, user, _settings(app_id, {WRITE: ASK, READ: ALLOW})
    )
    defaults = {WRITE: ASK, READ: ALLOW, "new.action": ALLOW}
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies=defaults,
        scheduled_task_id=task.id,
    ) == {WRITE: ALLOW, READ: DENY, "new.action": ASK}
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies=defaults,
        )[WRITE]
        == ASK
    )
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {WRITE: DENY}),
    )
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies=defaults,
            scheduled_task_id=task.id,
        )[WRITE]
        == DENY
    )


def test_reviewed_creation_does_not_copy_unseen_actions(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Daily",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        action_policies=_task_settings(app_id, {WRITE: ALLOW}),
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK, READ: ALLOW},
        scheduled_task_id=task.id,
    ) == {WRITE: ALLOW, READ: ASK}


def test_workspace_restrictions_override_and_preserve_saved_choices(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ALLOW}))
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: DENY}, users_can_manage=None
    )
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies={WRITE: ASK},
        )[WRITE]
        == DENY
    )
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: DENY}))
    replace_workspace_action_policies(
        db_session, app_id, policies={}, users_can_manage=False
    )
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies={WRITE: ASK},
        )[WRITE]
        == ASK
    )
    replace_workspace_action_policies(
        db_session, app_id, policies=None, users_can_manage=True
    )
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies={WRITE: ASK},
        )[WRITE]
        == ALLOW
    )


def test_save_replaces_scope_and_reset_follows_workspace(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    save_user_action_policies(
        db_session, user, _settings(app_id, {WRITE: ALLOW, READ: DENY})
    )
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ASK}))
    projection = next(
        app
        for app in list_action_policies(db_session, user)
        if app.gated_app_id == app_id
    )
    read = next(action for action in projection.actions if action.action_id == READ)
    assert read.stored_policy is None
    assert read.effective_policy == ALLOW
    save_user_action_policies(db_session, user, _settings(app_id, {}))
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies={WRITE: ALLOW},
        )[WRITE]
        == ALLOW
    )


def test_unknown_action_and_foreign_task_are_rejected(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    with pytest.raises(OnyxError, match="Unknown app action"):
        save_user_action_policies(
            db_session, user, _settings(app_id, {"unknown": ALLOW})
        )
    other_user = User(
        id=uuid4(),
        email=f"other-{uuid4()}@example.com",
        hashed_password="unused",
        is_active=True,
        is_verified=True,
    )
    db_session.add(other_user)
    db_session.flush()
    other_task = create_scheduled_task(
        db_session=db_session,
        user_id=other_user.id,
        name="Other task",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        action_policies=[],
    )
    with pytest.raises(OnyxError, match="Scheduled task not found"):
        update_scheduled_task(
            db_session=db_session,
            user_id=user.id,
            task_id=other_task.id,
            action_policies=_task_settings(app_id, {WRITE: ALLOW}),
        )


def test_mcp_uses_same_settings_and_access_rules(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, _ = owner_and_app
    server = create_mcp_server__no_commit(
        owner_email=user.email,
        name="Permission MCP",
        description=None,
        server_url="https://example.com/mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
        is_public=True,
    )
    update_mcp_server__no_commit(
        server_id=server.id, db_session=db_session, available_in_craft=True
    )
    db_session.add(
        Tool(name="send_report", description="Send report", mcp_server_id=server.id)
    )
    db_session.flush()
    app_id = get_or_create_gated_app_id(db_session, GatedAppKind.MCP_SERVER, server.id)
    save_user_action_policies(
        db_session, user, _settings(app_id, {"send_report": ALLOW})
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={"send_report": ASK},
    ) == {"send_report": ALLOW}
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="MCP report",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
    )
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {"send_report": ALLOW}),
    )
    upsert_mcp_server_user_preferences__no_commit(
        server.id, user.id, db_session, enabled_in_craft=False
    )
    db_session.flush()
    assert not get_craft_enabled_mcp_servers(db_session, user, server_ids={server.id})
    personal = list_action_policies(db_session, user, gated_app_id=app_id)
    assert personal[0].actions[0].effective_policy == ALLOW
    save_user_action_policies(db_session, user, _settings(app_id, {"send_report": ASK}))
    assert (
        list_action_policies(db_session, user, gated_app_id=app_id)[0]
        .actions[0]
        .effective_policy
        == ASK
    )
    task_catalog = list_action_policies(
        db_session, user, task_id=task.id, gated_app_id=app_id
    )
    assert task_catalog[0].enabled is True
    assert task_catalog[0].actions[0].effective_policy == ALLOW
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=[],
    )
    assert get_task_action_policies(db_session, task.id) == _task_settings(
        app_id, {"send_report": ALLOW}
    )
    update_mcp_server__no_commit(
        server_id=server.id, db_session=db_session, available_in_craft=False
    )
    save_user_action_policies(
        db_session, user, _settings(app_id, {"send_report": ALLOW})
    )
    assert (
        list_action_policies(
            db_session, user, target=(GatedAppKind.MCP_SERVER, server.id)
        )[0]
        .actions[0]
        .effective_policy
        == ALLOW
    )
    assert not any(
        view.kind == "mcp_server" and view.target_id == server.id
        for view in list_action_policies(db_session, user)
    )
    with pytest.raises(OnyxError, match="App is unavailable"):
        update_scheduled_task(
            db_session=db_session,
            user_id=user.id,
            task_id=task.id,
            action_policies=_task_settings(app_id, {"send_report": ASK}),
        )


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


def test_mcp_read_only_tool_defaults_to_always_until_an_admin_asks(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, _ = owner_and_app
    server = create_mcp_server__no_commit(
        owner_email=user.email,
        name="Read-only MCP",
        description=None,
        server_url="https://read-only.example.com/mcp",
        auth_type=None,
        transport=None,
        auth_performer=None,
        db_session=db_session,
        is_public=True,
    )
    update_mcp_server__no_commit(
        server_id=server.id, db_session=db_session, available_in_craft=True
    )
    tools = [
        Tool(name=name, description=name, mcp_server_id=server.id, mcp_read_only=hint)
        for name, hint in (("read", True), ("write", False), ("plain", None))
    ]
    db_session.add_all(tools)
    db_session.flush()
    app_id = get_or_create_gated_app_id(db_session, GatedAppKind.MCP_SERVER, server.id)

    def resolved() -> dict[str, ActionPolicy]:
        return resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies=get_mcp_tool_default_policies(db_session, server.id),
        )

    def chat_resolved() -> dict[str, ActionPolicy]:
        # Chat tool construction reads the hint from the captured configuration.
        configured = [ToolConfiguration.model_validate(tool) for tool in tools]
        return resolve_user_action_policies(
            db_session,
            user_id=user.id,
            app_kind=GatedAppKind.MCP_SERVER,
            default_policies_by_target={
                server.id: {
                    tool.name: mcp_tool_default_policy(tool.mcp_read_only)
                    for tool in configured
                }
            },
        )[server.id]

    def admin_view() -> dict[str, ActionPolicy]:
        (app,) = list_action_policies(db_session, user, gated_app_id=app_id, admin=True)
        return {a.action_id: a.workspace_policy for a in app.actions}

    defaults = {"read": ALLOW, "write": ASK, "plain": ASK}
    assert resolved() == defaults
    assert chat_resolved() == defaults
    assert admin_view() == defaults

    replace_workspace_action_policies(db_session, app_id, {"read": ASK})
    asked = {"read": ASK, "write": ASK, "plain": ASK}
    assert resolved() == asked
    assert chat_resolved() == asked
    assert admin_view() == asked


def test_reviewed_disabled_choice_is_copied_and_stays_independent(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: DENY}, users_can_manage=True
    )
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Daily",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        action_policies=_task_settings(app_id, {WRITE: DENY}),
    )
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: ALLOW}, users_can_manage=True
    )
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies={WRITE: ASK},
            scheduled_task_id=task.id,
        )[WRITE]
        == DENY
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
        action_policies=[],
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


def test_reset_clears_inactive_and_hidden_personal_choices(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, app_id = owner_and_app
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ALLOW}))
    db_session.add(
        UserActionPolicy(
            user_id=user.id,
            gated_app_id=app_id,
            action_id="retired.action",
            policy=ALLOW,
        )
    )
    db_session.flush()
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: DENY}, users_can_manage=True
    )
    save_user_action_policies(db_session, user, _settings(app_id, {}))
    replace_workspace_action_policies(
        db_session, app_id, policies={}, users_can_manage=True
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK, "retired.action": ASK},
    ) == {WRITE: ASK, "retired.action": ASK}
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ALLOW}))
    replace_workspace_action_policies(
        db_session, app_id, policies=None, users_can_manage=False
    )
    with pytest.raises(OnyxError, match="prevent this action policy change"):
        save_user_action_policies(db_session, user, _settings(app_id, {}))
    replace_workspace_action_policies(
        db_session, app_id, policies=None, users_can_manage=True
    )
    assert (
        resolve_action_policies(
            db_session,
            user_id=user.id,
            gated_app_id=app_id,
            catalog_policies={WRITE: ASK},
        )[WRITE]
        == ALLOW
    )


def test_reset_then_edit_removes_omitted_locked_choice(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    save_user_action_policies(
        db_session, user, _settings(app_id, {WRITE: ALLOW, READ: DENY})
    )
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: DENY}, users_can_manage=True
    )
    # Reset clears the draft. A later edit submits only that edited action.
    save_user_action_policies(db_session, user, _settings(app_id, {READ: ASK}))
    replace_workspace_action_policies(
        db_session, app_id, policies={}, users_can_manage=True
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK, READ: ALLOW},
    ) == {WRITE: ASK, READ: ASK}


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


def test_task_apps_start_disabled_and_keep_independent_saved_choices(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, app_id = owner_and_app
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Daily",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
    )
    assert get_task_action_policies(db_session, task.id) == []
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ALLOW}))
    view = list_action_policies(db_session, user, gated_app_id=app_id, task_id=task.id)[
        0
    ]
    assert view.enabled is False
    assert (
        next(
            action for action in view.actions if action.action_id == WRITE
        ).effective_policy
        == ASK
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK},
        scheduled_task_id=task.id,
    ) == {WRITE: DENY}
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {WRITE: ALLOW}),
    )
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ASK}))
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK},
        scheduled_task_id=task.id,
    ) == {WRITE: ALLOW}
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {WRITE: ALLOW}, enabled=False),
    )
    replace_workspace_action_policies(
        db_session, app_id, policies={WRITE: ALLOW}, users_can_manage=False
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK},
        scheduled_task_id=task.id,
    ) == {WRITE: DENY}
    view = list_action_policies(db_session, user, gated_app_id=app_id, task_id=task.id)[
        0
    ]
    assert view.enabled is False
    assert (
        next(
            action for action in view.actions if action.action_id == WRITE
        ).stored_policy
        == ALLOW
    )
    replace_workspace_action_policies(
        db_session, app_id, policies={}, users_can_manage=True
    )
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {WRITE: ALLOW}),
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ASK},
        scheduled_task_id=task.id,
    ) == {WRITE: ALLOW}
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=None,
        catalog_policies={WRITE: ALLOW},
        scheduled_task_id=task.id,
    ) == {WRITE: DENY}


def test_task_can_enable_app_without_catalog_actions(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:

    user, _ = owner_and_app
    app = ExternalApp(
        name="Custom",
        app_type=ExternalAppType.CUSTOM,
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    )
    db_session.add(app)
    db_session.flush()
    app_id = get_or_create_gated_app_id(db_session, GatedAppKind.EXTERNAL_APP, app.id)
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Daily",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        action_policies=_task_settings(app_id, {}),
    )
    assert task_app_enabled(db_session, task.id, app_id)
    assert get_task_action_policies(db_session, task.id) == _task_settings(app_id, {})
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={"unknown": ASK},
        scheduled_task_id=task.id,
    ) == {"unknown": ASK}
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {}, enabled=False),
    )
    assert not task_app_enabled(db_session, task.id, app_id)


def test_empty_task_choices_do_not_copy_personal_settings(
    db_session: Session, owner_and_app: tuple[User, int]
) -> None:
    user, app_id = owner_and_app
    save_user_action_policies(db_session, user, _settings(app_id, {WRITE: ALLOW}))
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="Explicit choices",
        prompt="Report",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        action_policies=_task_settings(app_id, {}),
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ALLOW},
        scheduled_task_id=task.id,
    ) == {WRITE: ASK}
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {WRITE: ALLOW}),
    )
    update_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        task_id=task.id,
        action_policies=_task_settings(app_id, {}),
    )
    assert resolve_action_policies(
        db_session,
        user_id=user.id,
        gated_app_id=app_id,
        catalog_policies={WRITE: ALLOW},
        scheduled_task_id=task.id,
    ) == {WRITE: ASK}


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
