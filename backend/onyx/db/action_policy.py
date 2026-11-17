"""Old app identity rows, workspace policy storage and the personal policy view."""

from collections.abc import Collection
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.enums import (
    ActionPolicy,
    GatedAppKind,
)
from onyx.db.mcp import (
    get_mcp_servers_accessible_to_user,
    user_can_access_mcp_server,
)
from onyx.db.models import (
    ExternalApp,
    GatedApp,
    MCPServer,
    Tool,
    User,
    UserActionPolicy,
    WorkspaceActionPolicy,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import (
    ActionPolicySettingView,
    AppActionPoliciesView,
    EndpointDescriptor,
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
    db_session: Session, kind: GatedAppKind, target_id: int, *, for_update: bool = False
) -> int | None:
    """The ``gated_app`` row id for ``(kind, target_id)``, or ``None`` when the
    target has no identity row yet."""
    statement = select(GatedApp.id).where(_target_column(kind) == target_id)
    if for_update:
        statement = statement.with_for_update()
    return db_session.scalar(statement)


def get_or_create_gated_app_id(
    db_session: Session, kind: GatedAppKind, target_id: int, *, for_update: bool = False
) -> int:
    """The ``gated_app`` row id for ``(kind, target_id)``, creating it if absent.

    Race-safe: a concurrent insert is absorbed by ON CONFLICT DO NOTHING on the
    target's unique index, then re-selected. Flushes but does not commit.
    """
    existing = get_gated_app_id(db_session, kind, target_id, for_update=for_update)
    if existing is not None:
        return existing
    target_column = _target_column(kind).key
    db_session.execute(
        pg_insert(GatedApp)
        .values({target_column: target_id})
        .on_conflict_do_nothing(index_elements=[target_column])
    )
    db_session.flush()
    created = get_gated_app_id(db_session, kind, target_id, for_update=for_update)
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


def mcp_tool_default_policy(read_only: bool | None) -> ActionPolicy:
    """A server's readOnlyHint is unverified; it only relaxes the default."""
    return ActionPolicy.ALWAYS if read_only else ActionPolicy.ASK


def get_mcp_tool_default_policies(
    db_session: Session, mcp_server_id: int | None
) -> dict[str, ActionPolicy]:
    return {
        name: mcp_tool_default_policy(read_only)
        for name, read_only in db_session.execute(
            select(Tool.name, Tool.mcp_read_only).where(
                Tool.mcp_server_id == mcp_server_id
            )
        ).tuples()
    }


def _catalog_defaults(db_session: Session, app: GatedApp) -> dict[str, ActionPolicy]:
    if app.external_app_id is not None:
        external_app = db_session.get(ExternalApp, app.external_app_id)
        if external_app is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "App not found")
        return {
            endpoint.id: endpoint.default_policy
            for endpoint in get_endpoint_catalog(external_app.app_type)
        }
    return get_mcp_tool_default_policies(db_session, app.mcp_server_id)


def effective_action_policy(
    workspace_policy: ActionPolicy,
    users_can_manage_policies: bool,
    stored_policy: ActionPolicy | None,
) -> ActionPolicy:
    if workspace_policy == ActionPolicy.DENY or not users_can_manage_policies:
        return workspace_policy
    if stored_policy is not None:
        return stored_policy
    return workspace_policy


def _stored_policies(
    db_session: Session,
    user_id: UUID,
    gated_app_ids: Collection[int],
) -> dict[int, dict[str, ActionPolicy]]:
    """The owner's stored choices, by GatedApp ID."""
    rows = db_session.execute(
        select(
            UserActionPolicy.gated_app_id,
            UserActionPolicy.action_id,
            UserActionPolicy.policy,
        ).where(
            UserActionPolicy.user_id == user_id,
            UserActionPolicy.gated_app_id.in_(gated_app_ids),
        )
    )
    stored: dict[int, dict[str, ActionPolicy]] = {}
    for gated_app_id, action_id, policy in rows.tuples():
        stored.setdefault(gated_app_id, {})[action_id] = policy
    return stored


def list_action_policies(
    db_session: Session,
    user: User,
    *,
    gated_app_id: int | None = None,
    target: tuple[GatedAppKind, int] | None = None,
) -> list[AppActionPoliciesView]:
    """Read the catalog and the personal policy rows of one app. Never creates
    rows. A personal read covers every MCP server the user can access,
    because chat uses MCP servers too."""
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
    external_apps = {
        app.id: app
        for app in db_session.scalars(
            select(ExternalApp).where(
                ExternalApp.id.in_(external_ids), ExternalApp.enabled.is_(True)
            )
        )
    }
    server_ids = {app.mcp_server_id for app in apps if app.mcp_server_id is not None}
    servers = get_mcp_servers_accessible_to_user(
        user, db_session, server_ids=server_ids
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
    for app_id, action_id, policy in db_session.execute(
        select(
            WorkspaceActionPolicy.gated_app_id,
            WorkspaceActionPolicy.action_id,
            WorkspaceActionPolicy.policy,
        ).where(WorkspaceActionPolicy.gated_app_id.in_(app_ids))
    ):
        workspace_by_app.setdefault(app_id, {})[action_id] = policy
    user_by_app = _stored_policies(db_session, user.id, app_ids)
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
                    default_policy=mcp_tool_default_policy(tool.mcp_read_only),
                )
                for name, tool in sorted(tools_by_server.get(server.id, {}).items())
            ]
        workspace_overrides = workspace_by_app.get(app.id, {})
        stored = user_by_app.get(app.id, {})
        actions: list[ActionPolicySettingView] = []
        for action in catalog:
            workspace = workspace_overrides.get(action.action_id, action.default_policy)
            lock: Literal["workspace_disabled", "workspace_managed"] | None = None
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
                    effective_policy=effective_action_policy(
                        workspace,
                        app.users_can_manage_policies,
                        stored.get(action.action_id),
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
                actions=actions,
            )
        )
    if not result:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "App is unavailable")
    return result


def _load_workspace_rules(
    db_session: Session,
    user: User,
    gated_app_id: int,
) -> tuple[GatedApp, dict[str, ActionPolicy]]:
    """Check app access and read the rules used to validate personal saves."""
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
        if server is None or not user_can_access_mcp_server(
            user, server.id, db_session
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




def users_can_manage_policies(
    db_session: Session, kind: GatedAppKind, target_id: int
) -> bool:
    value = db_session.scalar(
        select(GatedApp.users_can_manage_policies).where(
            _target_column(kind) == target_id
        )
    )
    return value if value is not None else True


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
