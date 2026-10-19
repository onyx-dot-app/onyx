"""Shared app identity, action policy storage, views, and execution decisions."""

from typing import Literal
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.enums import (
    ActionPolicy,
    GatedAppKind,
    ScheduledTaskRunStatus,
    SessionOrigin,
)
from onyx.db.mcp import (
    get_craft_enabled_mcp_servers,
    user_can_access_mcp_server,
)
from onyx.db.models import (
    BuildSession,
    ExternalApp,
    GatedApp,
    MCPServer,
    ScheduledTask,
    ScheduledTaskActionPolicy,
    ScheduledTaskEnabledApp,
    ScheduledTaskRun,
    Tool,
    User,
    UserActionPolicy,
    WorkspaceActionPolicy,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import (
    ActionPolicySettingView,
    AppActionPolicies,
    AppActionPoliciesView,
    EndpointDescriptor,
    TaskAppActionPolicies,
)
from onyx.external_apps.providers.registry import (
    get_endpoint_catalog,
    normalize_action_policies,
)


def _target_column(kind: GatedAppKind) -> InstrumentedAttribute[int | None]:
    return (
        GatedApp.external_app_id
        if kind is GatedAppKind.EXTERNAL_APP
        else GatedApp.mcp_server_id
    )


def get_gated_app_id(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> int | None:
    """The ``gated_app`` row id for ``(kind, target_id)``, or ``None`` when the
    target has no identity row yet."""
    return db_session.scalar(
        select(GatedApp.id).where(_target_column(kind) == target_id)
    )


def get_or_create_gated_app_id(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> int:
    """The ``gated_app`` row id for ``(kind, target_id)``, creating it if absent.

    Race-safe: a concurrent insert is absorbed by ON CONFLICT DO NOTHING on the
    target's unique index, then re-selected. Flushes but does not commit.
    """
    existing = get_gated_app_id(db_session, kind, target_id)
    if existing is not None:
        return existing
    target_column = _target_column(kind).key
    db_session.execute(
        pg_insert(GatedApp)
        .values({target_column: target_id})
        .on_conflict_do_nothing(index_elements=[target_column])
    )
    db_session.flush()
    created = get_gated_app_id(db_session, kind, target_id)
    if created is None:
        # Unreachable barring a concurrent delete: we just inserted, or a
        # concurrent writer did.
        raise RuntimeError(
            f"gated_app row missing after insert for kind {kind} target_id {target_id}"
        )
    return created


def get_workspace_action_policies(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> dict[str, ActionPolicy]:
    """The target's stored action policy overrides as
    ``{action_id: policy}``; ``{}`` when none are set. Sparse — only actions an
    admin has explicitly set. One query: joins ``workspace_action_policy`` to
    ``gated_app`` (this runs on the request matching path)."""
    rows = db_session.execute(
        select(WorkspaceActionPolicy.action_id, WorkspaceActionPolicy.policy)
        .join(GatedApp, GatedApp.id == WorkspaceActionPolicy.gated_app_id)
        .where(_target_column(kind) == target_id)
    ).all()
    return {action_id: policy for action_id, policy in rows}  # noqa: C416  # unpacking types the SQLAlchemy Row


def _catalog_defaults(db_session: Session, app: GatedApp) -> dict[str, ActionPolicy]:
    if app.external_app_id is not None:
        external_app = db_session.get(ExternalApp, app.external_app_id)
        if external_app is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "App not found")
        return {
            endpoint.id: endpoint.default_policy
            for endpoint in get_endpoint_catalog(external_app.app_type)
        }
    return dict.fromkeys(
        db_session.scalars(
            select(Tool.name).where(Tool.mcp_server_id == app.mcp_server_id)
        ),
        ActionPolicy.ASK,
    )


def replace_workspace_action_policies(
    db_session: Session,
    gated_app_id: int,
    policies: dict[str, ActionPolicy] | None,
    *,
    users_can_manage: bool | None = None,
) -> None:
    """Validate and replace workspace choices. Omitted fields remain unchanged."""
    app = db_session.scalar(
        select(GatedApp)
        .where(GatedApp.id == gated_app_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if app is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "App not found")
    if policies is not None:
        policies = normalize_action_policies(
            policies, _catalog_defaults(db_session, app)
        )
        db_session.execute(
            delete(WorkspaceActionPolicy).where(
                WorkspaceActionPolicy.gated_app_id == gated_app_id
            )
        )
        if policies:
            db_session.execute(
                insert(WorkspaceActionPolicy),
                [
                    {
                        "gated_app_id": gated_app_id,
                        "action_id": action_id,
                        "policy": policy,
                    }
                    for action_id, policy in policies.items()
                ],
            )
    if users_can_manage is not None:
        app.users_can_manage_policies = users_can_manage
    db_session.flush()


def effective_action_policy(
    workspace_policy: ActionPolicy,
    users_can_manage_policies: bool,
    stored_policy: ActionPolicy | None,
    *,
    is_scheduled_task: bool,
) -> ActionPolicy:
    if workspace_policy == ActionPolicy.DENY or not users_can_manage_policies:
        return workspace_policy
    if stored_policy is not None:
        return stored_policy
    return ActionPolicy.ASK if is_scheduled_task else workspace_policy


def resolve_action_policies(
    db_session: Session,
    *,
    user_id: UUID,
    gated_app_id: int | None,
    catalog_policies: dict[str, ActionPolicy],
    scheduled_task_id: UUID | None = None,
) -> dict[str, ActionPolicy]:
    """Resolve catalog defaults against current workspace and owner settings."""
    if scheduled_task_id is not None and (
        gated_app_id is None
        or not task_app_enabled(db_session, scheduled_task_id, gated_app_id)
    ):
        return dict.fromkeys(catalog_policies, ActionPolicy.DENY)
    workspace = dict(catalog_policies)
    stored: dict[str, ActionPolicy] = {}
    users_can_manage = True
    if gated_app_id is not None:
        # Query columns, not identity-map objects: repeated requests need live values.
        users_can_manage = db_session.scalar(
            select(GatedApp.users_can_manage_policies).where(
                GatedApp.id == gated_app_id
            )
        )
        if users_can_manage is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "App permissions no longer exist")
        workspace.update(
            dict(
                db_session.execute(
                    select(
                        WorkspaceActionPolicy.action_id,
                        WorkspaceActionPolicy.policy,
                    ).where(WorkspaceActionPolicy.gated_app_id == gated_app_id)
                )
                .tuples()
                .all()
            )
        )
        stored = _stored_policies(db_session, user_id, gated_app_id, scheduled_task_id)
    return {
        action_id: effective_action_policy(
            workspace[action_id],
            users_can_manage,
            stored.get(action_id),
            is_scheduled_task=scheduled_task_id is not None,
        )
        for action_id in catalog_policies
    }


def get_active_scheduled_task_context(
    db_session: Session, session_id: UUID
) -> tuple[UUID, UUID] | None:
    """Return running task authority; reject inactive scheduled sessions.

    Only interactive and Slack sessions can return None and use personal policies.
    """
    row = db_session.execute(
        select(
            BuildSession.origin,
            ScheduledTaskRun.id,
            ScheduledTaskRun.task_id,
            ScheduledTaskRun.status,
        )
        .outerjoin(ScheduledTaskRun, ScheduledTaskRun.session_id == BuildSession.id)
        .where(BuildSession.id == session_id)
    ).first()
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session no longer exists")
    origin, run_id, task_id, status = row
    if run_id is not None and status == ScheduledTaskRunStatus.RUNNING:
        return run_id, task_id
    if run_id is not None or origin == SessionOrigin.SCHEDULED:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Scheduled execution is no longer active",
        )
    return None


def task_app_enabled(
    db_session: Session, task_id: UUID, gated_app_id: int | None
) -> bool:
    if gated_app_id is None:
        return False
    return (
        db_session.scalar(
            select(ScheduledTaskEnabledApp.gated_app_id).where(
                ScheduledTaskEnabledApp.scheduled_task_id == task_id,
                ScheduledTaskEnabledApp.gated_app_id == gated_app_id,
            )
        )
        is not None
    )


def _stored_policies(
    db_session: Session, user_id: UUID, gated_app_id: int, task_id: UUID | None
) -> dict[str, ActionPolicy]:
    if task_id is not None:
        rows = db_session.execute(
            select(
                ScheduledTaskActionPolicy.action_id,
                ScheduledTaskActionPolicy.policy,
            ).where(
                ScheduledTaskActionPolicy.scheduled_task_id == task_id,
                ScheduledTaskActionPolicy.gated_app_id == gated_app_id,
            )
        )
    else:
        rows = db_session.execute(
            select(UserActionPolicy.action_id, UserActionPolicy.policy).where(
                UserActionPolicy.user_id == user_id,
                UserActionPolicy.gated_app_id == gated_app_id,
            )
        )
    return dict(rows.tuples().all())


def list_action_policies(
    db_session: Session,
    user: User,
    *,
    gated_app_id: int | None = None,
    target: tuple[GatedAppKind, int] | None = None,
    task_id: UUID | None = None,
    admin: bool = False,
) -> list[AppActionPoliciesView]:
    """Read accessible catalogs and policy rows in batches. Never creates rows.

    Task ownership is checked by the scheduled-task endpoint before this read.
    """
    query = (
        select(GatedApp)
        .order_by(GatedApp.external_app_id.is_(None), GatedApp.id)
        .execution_options(populate_existing=True)
    )
    if gated_app_id is not None:
        query = query.where(GatedApp.id == gated_app_id)
    if target is not None:
        query = query.where(_target_column(target[0]) == target[1])
    apps = list(db_session.scalars(query))
    external_ids = [
        app.external_app_id for app in apps if app.external_app_id is not None
    ]
    external_query = select(ExternalApp).where(ExternalApp.id.in_(external_ids))
    if not admin:
        external_query = external_query.where(ExternalApp.enabled.is_(True))
    external_apps = {app.id: app for app in db_session.scalars(external_query)}
    server_ids = {app.mcp_server_id for app in apps if app.mcp_server_id is not None}
    servers = (
        list(db_session.scalars(select(MCPServer).where(MCPServer.id.in_(server_ids))))
        if admin
        else get_craft_enabled_mcp_servers(
            db_session,
            user,
            server_ids=server_ids,
            include_personal_disabled=True,
        )
    )
    mcp_servers = {server.id: server for server in servers if server.id in server_ids}
    tools_by_server: dict[int, dict[str, Tool]] = {}
    for tool in db_session.scalars(
        select(Tool).where(Tool.mcp_server_id.in_(mcp_servers))
    ):
        if tool.mcp_server_id is not None:
            tools_by_server.setdefault(tool.mcp_server_id, {})[tool.name] = tool
    app_ids = [app.id for app in apps]
    workspace_by_app: dict[int, dict[str, ActionPolicy]] = {}
    user_by_app: dict[int, dict[str, ActionPolicy]] = {}
    task_by_app: dict[int, dict[str, ActionPolicy]] = {}
    enabled_ids: set[int] = set()
    for app_id, action_id, policy in db_session.execute(
        select(
            WorkspaceActionPolicy.gated_app_id,
            WorkspaceActionPolicy.action_id,
            WorkspaceActionPolicy.policy,
        ).where(WorkspaceActionPolicy.gated_app_id.in_(app_ids))
    ):
        workspace_by_app.setdefault(app_id, {})[action_id] = policy
    if not admin and task_id is None:
        for app_id, action_id, policy in db_session.execute(
            select(
                UserActionPolicy.gated_app_id,
                UserActionPolicy.action_id,
                UserActionPolicy.policy,
            ).where(
                UserActionPolicy.gated_app_id.in_(app_ids),
                UserActionPolicy.user_id == user.id,
            )
        ):
            user_by_app.setdefault(app_id, {})[action_id] = policy
    if task_id is not None:
        for app_id, action_id, policy in db_session.execute(
            select(
                ScheduledTaskActionPolicy.gated_app_id,
                ScheduledTaskActionPolicy.action_id,
                ScheduledTaskActionPolicy.policy,
            ).where(
                ScheduledTaskActionPolicy.gated_app_id.in_(app_ids),
                ScheduledTaskActionPolicy.scheduled_task_id == task_id,
            )
        ):
            task_by_app.setdefault(app_id, {})[action_id] = policy
        enabled_ids = set(
            db_session.scalars(
                select(ScheduledTaskEnabledApp.gated_app_id).where(
                    ScheduledTaskEnabledApp.scheduled_task_id == task_id
                )
            )
        )
    result: list[AppActionPoliciesView] = []
    for app in apps:
        if app.external_app_id is not None:
            external = external_apps.get(app.external_app_id)
            if external is None:
                continue
            name = external.name
            app_type = external.app_type
            catalog = [
                EndpointDescriptor(
                    action_id=endpoint.id,
                    normalised_name=endpoint.normalised_name,
                    description=endpoint.description,
                    default_policy=endpoint.default_policy,
                )
                for endpoint in get_endpoint_catalog(app_type)
            ]
        else:
            server = mcp_servers.get(app.target_id)
            if server is None:
                continue
            name = server.name
            app_type = None
            catalog = [
                EndpointDescriptor(
                    action_id=name,
                    normalised_name=tool.display_name or name,
                    description=tool.description or "",
                    default_policy=ActionPolicy.ASK,
                )
                for name, tool in sorted(tools_by_server.get(server.id, {}).items())
            ]
        workspace_overrides = workspace_by_app.get(app.id, {})
        user_overrides = user_by_app.get(app.id, {})
        stored = (
            workspace_overrides
            if admin
            else task_by_app.get(app.id, {})
            if task_id is not None
            else user_overrides
        )
        actions: list[ActionPolicySettingView] = []
        for action in catalog:
            workspace = workspace_overrides.get(action.action_id, action.default_policy)
            lock: Literal["workspace_disabled", "workspace_managed"] | None = None
            if not admin:
                if workspace == ActionPolicy.DENY:
                    lock = "workspace_disabled"
                elif not app.users_can_manage_policies:
                    lock = "workspace_managed"
            actions.append(
                ActionPolicySettingView(
                    action_id=action.action_id,
                    normalised_name=action.normalised_name,
                    description=action.description,
                    workspace_policy=workspace,
                    effective_policy=workspace
                    if admin
                    else effective_action_policy(
                        workspace,
                        app.users_can_manage_policies,
                        stored.get(action.action_id),
                        is_scheduled_task=task_id is not None,
                    ),
                    stored_policy=stored.get(action.action_id),
                    editable=lock is None,
                    lock_reason=lock,
                )
            )
        result.append(
            AppActionPoliciesView(
                gated_app_id=app.id,
                kind="external_app"
                if app.external_app_id is not None
                else "mcp_server",
                target_id=app.target_id,
                name=name,
                app_type=app_type,
                users_can_manage_policies=app.users_can_manage_policies,
                enabled=app.id in enabled_ids if task_id is not None else None,
                actions=actions,
            )
        )
    if (gated_app_id is not None or target is not None) and not result:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "App is unavailable")
    return result


def _load_workspace_rules(
    db_session: Session,
    user: User,
    gated_app_id: int,
) -> tuple[GatedApp, dict[str, ActionPolicy]]:
    """Check app access and read the rules used to validate personal/task saves."""
    app = db_session.get(GatedApp, gated_app_id, populate_existing=True)
    if app is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "App is unavailable")
    if app.external_app_id is not None:
        external = db_session.get(
            ExternalApp, app.external_app_id, populate_existing=True
        )
        if external is None or not external.enabled:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "App is unavailable")
    else:
        server = db_session.get(MCPServer, app.mcp_server_id, populate_existing=True)
        if (
            server is None
            or not server.available_in_craft
            or not user_can_access_mcp_server(user, server.id, db_session)
        ):
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "App is unavailable")
    workspace = _catalog_defaults(db_session, app)
    overrides = get_workspace_action_policies(db_session, app.kind, app.target_id)
    return app, {
        action_id: overrides.get(action_id, policy)
        for action_id, policy in workspace.items()
    }


def _validate_owner_choices(
    workspace: dict[str, ActionPolicy],
    users_can_manage: bool,
    submitted: dict[str, ActionPolicy],
    stored: dict[str, ActionPolicy],
) -> set[str]:
    """Validate submitted choices and return the actions the owner can change."""
    if submitted.keys() - workspace.keys():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Unknown app action")
    editable = {
        action_id
        for action_id, policy in workspace.items()
        if users_can_manage and policy != ActionPolicy.DENY
    }
    for action_id, policy in submitted.items():
        if action_id not in editable and policy not in (
            workspace[action_id],
            stored.get(action_id),
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Workspace settings prevent this action policy change",
            )
    return editable


def save_user_action_policies(
    db_session: Session,
    user: User,
    setting: AppActionPolicies,
) -> None:
    """Replace personal choices. An empty mapping resets all personal overrides."""
    db_session.execute(select(User).filter_by(id=user.id).with_for_update(of=User))
    db_session.execute(
        select(GatedApp.id).where(GatedApp.id == setting.gated_app_id).with_for_update()
    )
    app, workspace = _load_workspace_rules(db_session, user, setting.gated_app_id)
    if not app.users_can_manage_policies:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Workspace settings prevent this action policy change",
        )
    stored = _stored_policies(db_session, user.id, app.id, None)
    editable = _validate_owner_choices(
        workspace, app.users_can_manage_policies, setting.action_policies, stored
    )
    values = {
        key: value for key, value in setting.action_policies.items() if key in editable
    }
    values.update(
        {
            key: value
            for key, value in stored.items()
            if key not in editable and key in setting.action_policies
        }
    )
    delete_query = delete(UserActionPolicy).where(
        UserActionPolicy.user_id == user.id,
        UserActionPolicy.gated_app_id == setting.gated_app_id,
    )
    if setting.action_policies:
        delete_query = delete_query.where(UserActionPolicy.action_id.in_(workspace))
    db_session.execute(delete_query)
    if values:
        db_session.execute(
            insert(UserActionPolicy),
            [
                {
                    "user_id": user.id,
                    "gated_app_id": setting.gated_app_id,
                    "action_id": key,
                    "policy": value,
                }
                for key, value in values.items()
            ],
        )


def replace_task_action_policies(
    db_session: Session,
    user: User,
    task: ScheduledTask,
    settings: list[TaskAppActionPolicies],
) -> None:
    """Save explicit app choices for an owned, locked task. Empty means no choices.

    The task create/update operation owns authorization and transaction locking.
    Disabled apps retain the choices submitted by the editor, just like enabled apps.
    """
    ids = [setting.gated_app_id for setting in settings]
    if len(set(ids)) != len(ids):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "An app can appear only once")
    db_session.execute(
        select(GatedApp.id)
        .where(GatedApp.id.in_(ids))
        .order_by(GatedApp.id)
        .with_for_update()
    ).all()
    for setting in settings:
        app, workspace = _load_workspace_rules(db_session, user, setting.gated_app_id)
        stored = _stored_policies(db_session, user.id, app.id, task.id)
        editable = _validate_owner_choices(
            workspace, app.users_can_manage_policies, setting.action_policies, stored
        )
        values = {
            key: value
            for key, value in setting.action_policies.items()
            if key in editable
        }
        # Locked choices remain dormant until workspace restrictions are lifted.
        # On first save, retain the displayed workspace value for locked actions.
        values.update(
            {
                key: value
                for key, value in setting.action_policies.items()
                if key not in editable and key not in stored
            }
        )
        replace_ids = editable | values.keys()
        db_session.execute(
            delete(ScheduledTaskActionPolicy).where(
                ScheduledTaskActionPolicy.scheduled_task_id == task.id,
                ScheduledTaskActionPolicy.gated_app_id == setting.gated_app_id,
                ScheduledTaskActionPolicy.action_id.in_(replace_ids),
            )
        )
        if values:
            db_session.execute(
                insert(ScheduledTaskActionPolicy),
                [
                    {
                        "scheduled_task_id": task.id,
                        "gated_app_id": setting.gated_app_id,
                        "action_id": key,
                        "policy": value,
                    }
                    for key, value in values.items()
                ],
            )
        db_session.execute(
            delete(ScheduledTaskEnabledApp).where(
                ScheduledTaskEnabledApp.scheduled_task_id == task.id,
                ScheduledTaskEnabledApp.gated_app_id == setting.gated_app_id,
            )
        )
        if setting.enabled:
            db_session.add(
                ScheduledTaskEnabledApp(
                    scheduled_task_id=task.id, gated_app_id=setting.gated_app_id
                )
            )
    db_session.flush()


def get_task_action_policies(
    db_session: Session, task_id: UUID
) -> list[TaskAppActionPolicies]:
    grouped: dict[int, dict[str, ActionPolicy]] = {}
    for app_id, action_id, policy in db_session.execute(
        select(
            ScheduledTaskActionPolicy.gated_app_id,
            ScheduledTaskActionPolicy.action_id,
            ScheduledTaskActionPolicy.policy,
        ).where(ScheduledTaskActionPolicy.scheduled_task_id == task_id)
    ):
        grouped.setdefault(app_id, {})[action_id] = policy
    enabled_ids = set(
        db_session.scalars(
            select(ScheduledTaskEnabledApp.gated_app_id).where(
                ScheduledTaskEnabledApp.scheduled_task_id == task_id
            )
        )
    )
    for app_id in enabled_ids:
        grouped.setdefault(app_id, {})
    return [
        TaskAppActionPolicies(
            gated_app_id=app_id,
            enabled=app_id in enabled_ids,
            action_policies=policies,
        )
        for app_id, policies in sorted(grouped.items())
    ]


def users_can_manage_policies(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> bool:
    value = db_session.scalar(
        select(GatedApp.users_can_manage_policies).where(
            _target_column(kind) == target_id
        )
    )
    return value if value is not None else True
