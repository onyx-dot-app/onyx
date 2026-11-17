"""The public tool routes. Built-in tools come from the ``tool`` table. A
custom tool is an ``api`` integration with an OpenAPI schema: the routes read
and write the integration and return the id of its OpenAPI ``tool`` row."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permission_projection import tool_permissions
from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    Permission,
    PluginInstallationPolicy,
)
from onyx.db.integration import (
    IntegrationPluginRow,
    get_integration_by_id,
    get_openapi_tool_for_integration,
    list_integration_plugin_rows,
    list_openapi_tools_with_integration,
)
from onyx.db.integration_connection import (
    get_connection,
    upsert_connection__no_commit,
)
from onyx.db.models import Integration, Tool, User
from onyx.db.plugin import lock_plugin, set_plugin_preferences__no_commit
from onyx.db.plugin_access import load_user_plugin_states
from onyx.db.tools import get_tools
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import ConnectionSecret, read_connection_secret
from onyx.integrations.service import (
    create_integration__no_commit,
    delete_integration_for_user__no_commit,
    get_manageable_integration,
    manages_integration,
    update_integration__no_commit,
    validate_openapi_definition,
)
from onyx.server.features.integrations.models import (
    CredentialField,
    IntegrationCreate,
    IntegrationUpdate,
    OpenApiConfigInput,
)
from onyx.server.features.tool.models import (
    CustomToolCreate,
    CustomToolUpdate,
    Header,
    ToolSnapshot,
    ToolUserPreferences,
)
from onyx.server.features.tool.tool_visibility import should_expose_tool_to_fe
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    MethodSpec,
    openapi_to_method_specs,
)
from onyx.utils.encryption import is_masked_credential, mask_string

router = APIRouter(prefix="/tool")
admin_router = APIRouter(prefix="/admin/tool")

_DEFAULT_CHAT_POLICIES = frozenset(
    {PluginInstallationPolicy.DEFAULT, PluginInstallationPolicy.REQUIRED}
)


class _AuthSettings(BaseModel):
    auth_mode: IntegrationAuthMode
    auth_method: IntegrationAuthMethod | None
    header_template: dict[str, str] | None
    credential_fields: list[CredentialField] | None
    # The values of the organization connection, by header name.
    organization_fields: dict[str, str]


def _auth_settings(headers: list[Header], passthrough_auth: bool) -> _AuthSettings:
    """The integration sign-in of a custom tool. Passthrough sends the user's
    Onyx login with the static headers; plain headers become an encrypted
    organization connection, as in the credential import."""
    values = {header.key: header.value for header in headers if header.value}
    if passthrough_auth:
        if any(key.lower() == "authorization" for key in values):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Cannot use passthrough auth with custom authorization headers",
            )
        return _AuthSettings(
            auth_mode=IntegrationAuthMode.INDIVIDUAL,
            auth_method=IntegrationAuthMethod.ONYX_LOGIN,
            header_template={**values, "Authorization": "Bearer {access_token}"},
            credential_fields=None,
            organization_fields={},
        )
    if values:
        return _AuthSettings(
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={key: "{" + key + "}" for key in values},
            credential_fields=[
                CredentialField(key=key, label=key, secret=True) for key in values
            ],
            organization_fields=values,
        )
    return _AuthSettings(
        auth_mode=IntegrationAuthMode.NONE,
        auth_method=None,
        header_template=None,
        credential_fields=None,
        organization_fields={},
    )


def _refuse_oauth_config(oauth_config_id: int | None) -> None:
    if oauth_config_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth configs are no longer supported on custom tools. Set up OAuth "
            "sign-in on the integration (/admin/integrations).",
        )


def _check_default_chat_permission(enabled: bool | None, user: User) -> None:
    if enabled is not None and not has_global_permission(
        user, Permission.FULL_ADMIN_PANEL_ACCESS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only full admins can change default Chat availability",
        )


def _set_default_chat(
    integration: Integration, enabled: bool | None, db_session: Session
) -> None:
    """Default Chat availability is the install setting of the plugins that
    hold the integration: Installed by default, or the marketplace default."""
    if enabled is None:
        return
    for row in list_integration_plugin_rows([integration.id], db_session)[
        integration.id
    ]:
        plugin = lock_plugin(row.plugin_id, db_session)
        if plugin is not None:
            plugin.installation_policy = (
                PluginInstallationPolicy.DEFAULT if enabled else None
            )
    db_session.flush()


def _organization_fields(
    integration: Integration, db_session: Session
) -> dict[str, str]:
    connection = get_connection(db_session, integration.id, None)
    if connection is None:
        return {}
    return read_connection_secret(connection).fields


def _stored_headers(integration: Integration, db_session: Session) -> dict[str, str]:
    """The headers a call sends, with the organization values filled in."""
    fields = _organization_fields(integration, db_session)
    headers: dict[str, str] = {}
    for name, template in (integration.header_template or {}).items():
        if template == "Bearer {access_token}" and name.lower() == "authorization":
            continue
        if template.startswith("{") and template.endswith("}"):
            value = fields.get(template[1:-1])
            if value is not None:
                headers[name] = value
            continue
        headers[name] = template
    return headers


def _resolve_masked_headers(
    headers: list[Header], stored: dict[str, str]
) -> list[Header]:
    """A masked value means "keep the stored one", as the admin UI echoes
    what it read."""
    resolved: list[Header] = []
    for header in headers:
        if not is_masked_credential(header.value):
            resolved.append(header)
            continue
        stored_value = stored.get(header.key)
        if stored_value is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Header '{header.key}' was sent as a masked placeholder but has "
                "no stored value to keep. Send the actual header value.",
            )
        resolved.append(Header(key=header.key, value=stored_value))
    return resolved


def _save_organization_fields(
    integration: Integration, fields: dict[str, str], db_session: Session
) -> None:
    if not fields:
        return
    upsert_connection__no_commit(
        db_session,
        integration_id=integration.id,
        user_id=None,
        secret=ConnectionSecret(fields=fields).model_dump(mode="json"),
        expires_at=None,
        granted_scopes=None,
    )


def _alias_snapshot(
    tool: Tool,
    integration: Integration,
    plugins: list[IntegrationPluginRow],
    db_session: Session,
    *,
    user_enabled: bool = True,
    permissions: dict[str, bool] | None = None,
) -> ToolSnapshot:
    return ToolSnapshot(
        id=tool.id,
        name=integration.name,
        description=integration.description or "",
        definition=tool.openapi_schema,
        display_name=integration.name,
        in_code_tool_id=None,
        custom_headers=[
            {"key": name, "value": mask_string(value)}
            for name, value in _stored_headers(integration, db_session).items()
        ],
        passthrough_auth=integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN,
        mcp_server_id=None,
        user_id=(
            str(integration.created_by_user_id)
            if integration.created_by_user_id is not None
            else None
        ),
        oauth_config_id=None,
        oauth_config_name=None,
        enabled=integration.enabled,
        user_enabled_in_chat=user_enabled,
        default_chat_enabled=any(
            plugin.installation_policy in _DEFAULT_CHAT_POLICIES for plugin in plugins
        ),
        permissions=permissions or {},
        plugin_ids=[plugin.plugin_id for plugin in plugins],
    )


def _openapi_tool_or_404(tool_id: int, db_session: Session) -> tuple[Tool, Integration]:
    tool = db_session.get(Tool, tool_id)
    if (
        tool is None
        or tool.openapi_schema is None
        or tool.mcp_server_id is not None
        or tool.integration_id is None
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Tool with ID {tool_id} not found")
    integration = get_integration_by_id(tool.integration_id, db_session)
    if integration is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Tool with ID {tool_id} not found")
    return tool, integration


def _snapshot_for(
    tool: Tool, integration: Integration, db_session: Session
) -> ToolSnapshot:
    plugins = list_integration_plugin_rows([integration.id], db_session)[integration.id]
    return _alias_snapshot(tool, integration, plugins, db_session)


@admin_router.post("/custom", tags=PUBLIC_API_TAGS)
def create_custom_tool(
    tool_data: CustomToolCreate,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> ToolSnapshot:
    _check_default_chat_permission(tool_data.default_chat_enabled, user)
    _refuse_oauth_config(tool_data.oauth_config_id)
    validate_openapi_definition(tool_data.definition)
    auth = _auth_settings(tool_data.custom_headers or [], tool_data.passthrough_auth)
    integration = create_integration__no_commit(
        user,
        IntegrationCreate(
            for_organization=has_global_permission(user, Permission.MANAGE_ACTIONS),
            name=tool_data.name,
            description=tool_data.description,
            auth_mode=auth.auth_mode,
            auth_method=auth.auth_method,
            credential_fields=auth.credential_fields,
            header_template=auth.header_template,
            config=OpenApiConfigInput(openapi_spec=tool_data.definition),
        ),
        db_session,
    )
    _save_organization_fields(integration, auth.organization_fields, db_session)
    _set_default_chat(integration, tool_data.default_chat_enabled, db_session)
    db_session.commit()
    tool = get_openapi_tool_for_integration(integration.id, db_session)
    if tool is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The OpenAPI schema is missing.")
    return _snapshot_for(tool, integration, db_session)


@admin_router.put("/custom/{tool_id}", tags=PUBLIC_API_TAGS)
def update_custom_tool(
    tool_id: int,
    tool_data: CustomToolUpdate,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> ToolSnapshot:
    _check_default_chat_permission(tool_data.default_chat_enabled, user)
    if "oauth_config_id" in tool_data.model_fields_set:
        _refuse_oauth_config(tool_data.oauth_config_id)
    tool, integration = _openapi_tool_or_404(tool_id, db_session)
    integration = get_manageable_integration(
        user, integration.id, db_session, lock=True
    )
    if tool_data.definition is not None:
        validate_openapi_definition(tool_data.definition)

    update = IntegrationUpdate()
    if tool_data.name is not None:
        update.name = tool_data.name
    if tool_data.description is not None:
        update.description = tool_data.description
    if tool_data.definition is not None:
        update.config = OpenApiConfigInput(openapi_spec=tool_data.definition)

    organization_fields: dict[str, str] = {}
    if tool_data.custom_headers is not None or tool_data.passthrough_auth is not None:
        stored = _stored_headers(integration, db_session)
        headers = (
            _resolve_masked_headers(tool_data.custom_headers, stored)
            if tool_data.custom_headers is not None
            else [Header(key=key, value=value) for key, value in stored.items()]
        )
        passthrough = (
            tool_data.passthrough_auth
            if tool_data.passthrough_auth is not None
            else integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN
        )
        auth = _auth_settings(headers, passthrough)
        update.auth_mode = auth.auth_mode
        update.auth_method = auth.auth_method
        update.header_template = auth.header_template
        update.credential_fields = auth.credential_fields
        organization_fields = auth.organization_fields

    integration = update_integration__no_commit(
        user, integration.id, update, db_session
    )
    if organization_fields != _organization_fields(integration, db_session):
        _save_organization_fields(integration, organization_fields, db_session)
    _set_default_chat(integration, tool_data.default_chat_enabled, db_session)
    db_session.commit()
    return _snapshot_for(tool, integration, db_session)


@admin_router.delete("/custom/{tool_id}", tags=PUBLIC_API_TAGS)
def delete_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> None:
    _, integration = _openapi_tool_or_404(tool_id, db_session)
    delete_integration_for_user__no_commit(user, integration.id, db_session)
    db_session.commit()


class ValidateToolRequest(BaseModel):
    definition: dict[str, Any]


class ValidateToolResponse(BaseModel):
    methods: list[MethodSpec]


@admin_router.post("/custom/validate", tags=PUBLIC_API_TAGS)
def validate_tool(
    tool_data: ValidateToolRequest,
    _: User = Depends(require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)),
) -> ValidateToolResponse:
    validate_openapi_definition(tool_data.definition)
    return ValidateToolResponse(methods=openapi_to_method_specs(tool_data.definition))


def _openapi_snapshots(
    user: User, db_session: Session, *, managed_or_visible: bool
) -> list[ToolSnapshot]:
    """The custom tools the user can see through a plugin. With
    ``managed_or_visible``, also those the user manages, with the
    permissions stamped."""
    tools = list_openapi_tools_with_integration(db_session)
    integration_ids = [
        tool.integration_id for tool in tools if tool.integration_id is not None
    ]
    plugin_rows = list_integration_plugin_rows(integration_ids, db_session)
    states = {
        state.plugin_id: state
        for state in load_user_plugin_states([user.id], db_session)
    }
    snapshots: list[ToolSnapshot] = []
    for tool in tools:
        if tool.integration_id is None or tool.openapi_schema is None:
            continue
        integration = get_integration_by_id(tool.integration_id, db_session)
        if integration is None:
            continue
        plugins = plugin_rows.get(integration.id, [])
        visible = [plugin for plugin in plugins if plugin.plugin_id in states]
        can_manage = manages_integration(user, plugins)
        if not visible and not (managed_or_visible and can_manage):
            continue
        if not managed_or_visible and not integration.enabled:
            continue
        snapshots.append(
            _alias_snapshot(
                tool,
                integration,
                plugins,
                db_session,
                user_enabled=any(states[p.plugin_id].enabled for p in visible)
                if visible
                else True,
                permissions=(
                    tool_permissions(can_manage=can_manage)
                    if managed_or_visible
                    else None
                ),
            )
        )
    return snapshots


@router.get("/openapi", tags=PUBLIC_API_TAGS)
def list_openapi_tools(
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    return _openapi_snapshots(user, db_session, managed_or_visible=True)


@router.get("/{tool_id}", tags=PUBLIC_API_TAGS)
def get_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ToolSnapshot:
    tool = db_session.get(Tool, tool_id)
    if tool is not None and tool.in_code_tool_id is not None:
        return ToolSnapshot.from_model(tool)
    tool, integration = _openapi_tool_or_404(tool_id, db_session)
    for snapshot in _openapi_snapshots(user, db_session, managed_or_visible=True):
        if snapshot.id == tool.id:
            snapshot.permissions = {}
            return snapshot
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You can only view actions you manage, or ones a plugin you can see holds.",
    )


@router.patch("/{tool_id}/preferences", tags=PUBLIC_API_TAGS)
def update_tool_user_preferences(
    tool_id: int,
    request: ToolUserPreferences,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ToolUserPreferences:
    """Turn the plugins that hold the custom tool on or off for the user."""
    _, integration = _openapi_tool_or_404(tool_id, db_session)
    visible = {
        state.plugin_id for state in load_user_plugin_states([user.id], db_session)
    }
    plugin_ids = [
        row.plugin_id
        for row in list_integration_plugin_rows([integration.id], db_session)[
            integration.id
        ]
        if row.plugin_id in visible
    ]
    if not plugin_ids:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Plugin is not available"
        )
    set_plugin_preferences__no_commit(
        user.id, plugin_ids, request.enabled_in_chat, db_session
    )
    db_session.commit()
    return ToolUserPreferences(enabled_in_chat=request.enabled_in_chat)


@router.get("", tags=PUBLIC_API_TAGS)
def list_tools(
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    built_in: list[ToolSnapshot] = []
    for tool in get_tools(db_session, only_enabled=True):
        if tool.in_code_tool_id is None or not should_expose_tool_to_fe(tool):
            continue
        try:
            if not get_built_in_tool_by_id(tool.in_code_tool_id).is_available(
                db_session
            ):
                continue
        except KeyError:
            pass
        built_in.append(ToolSnapshot.from_model(tool))
    return built_in + _openapi_snapshots(user, db_session, managed_or_visible=False)
