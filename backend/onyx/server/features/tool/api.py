"""The public tool routes. Built-in tools come from the ``tool`` table. A
custom tool is an ``api`` integration with a REST ``api_app``: the routes read
and write the integration and return the id of its OpenAPI ``tool`` row."""

import json
from collections.abc import Sequence
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
    get_mcp_tool_with_integration,
    get_openapi_tool_for_integration,
    get_openapi_tool_with_integration,
    list_api_apps_by_integration,
    list_mcp_tools_with_integration,
    list_openapi_tools_with_integration,
)
from onyx.db.integration_access import (
    load_user_integration_states,
    set_integration_preferences__no_commit,
)
from onyx.db.integration_connection import (
    get_connection,
    list_connections,
    upsert_connection__no_commit,
)
from onyx.db.models import ApiApp, Integration, IntegrationConnection, Tool, User
from onyx.db.tools import get_tools, get_tools_by_ids
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import (
    ConnectionSecret,
    literal_header_value,
    read_connection_secret,
)
from onyx.integrations.connections import (
    MissingHeaderValueError,
    literal_headers,
    render_headers,
)
from onyx.integrations.service import (
    create_integration__no_commit,
    delete_integration_for_user__no_commit,
    get_manageable_integration,
    keep_masked_values,
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
    CustomToolAuthSettings,
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
    parse_openapi_document,
)
from onyx.utils.encryption import mask_string

router = APIRouter(prefix="/tool")
admin_router = APIRouter(prefix="/admin/tool")

_DEFAULT_CHAT_POLICIES = frozenset(
    {PluginInstallationPolicy.DEFAULT, PluginInstallationPolicy.REQUIRED}
)
_BEARER_TEMPLATE = "Bearer {access_token}"


def _auth_settings(
    headers: list[Header], passthrough_auth: bool
) -> CustomToolAuthSettings:
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
        return CustomToolAuthSettings(
            auth_mode=IntegrationAuthMode.INDIVIDUAL,
            auth_method=IntegrationAuthMethod.ONYX_LOGIN,
            header_template={
                **{key: literal_header_value(value) for key, value in values.items()},
                "Authorization": _BEARER_TEMPLATE,
            },
            credential_fields=None,
            organization_fields={},
        )
    if values:
        return CustomToolAuthSettings(
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={key: "{" + key + "}" for key in values},
            credential_fields=[
                CredentialField(key=key, label=key, secret=True) for key in values
            ],
            organization_fields=values,
        )
    return CustomToolAuthSettings(
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
    """Default Chat availability is the company install setting of the
    integration. On makes it Installed by default for each user, unless it
    is Required. Off makes an integration that is Installed by default or
    Required Available; a private integration stays private. The caller
    locked the integration."""
    if enabled is None:
        return
    is_default_chat = integration.installation_policy in _DEFAULT_CHAT_POLICIES
    if enabled and not is_default_chat:
        integration.installation_policy = PluginInstallationPolicy.DEFAULT
    elif not enabled and is_default_chat:
        integration.installation_policy = PluginInstallationPolicy.AVAILABLE
    db_session.flush()


def _organization_secret(connection: IntegrationConnection | None) -> ConnectionSecret:
    if connection is None:
        return ConnectionSecret()
    return read_connection_secret(connection)


def _stored_headers(
    integration: Integration, organization: IntegrationConnection | None
) -> dict[str, str]:
    """The headers a call sends, with the organization values filled in. A
    migrated tool keeps its headers on the organization connection."""
    secret = _organization_secret(organization)
    headers = literal_headers(secret.headers)
    for name, template in (integration.header_template or {}).items():
        if template == _BEARER_TEMPLATE and name.lower() == "authorization":
            continue
        try:
            headers.update(
                render_headers({name: template}, ConnectionSecret(fields=secret.fields))
            )
        except MissingHeaderValueError:
            continue
    return headers


def _resolve_masked_headers(
    headers: list[Header], stored: dict[str, str]
) -> list[Header]:
    values = keep_masked_values(
        {header.key: header.value for header in headers}, stored
    )
    return [Header(key=key, value=value) for key, value in values.items()]


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
    organization: IntegrationConnection | None,
    api_app: ApiApp | None,
) -> ToolSnapshot:
    return ToolSnapshot(
        id=tool.id,
        name=integration.name,
        description=integration.description or "",
        definition=(
            parse_openapi_document(api_app.openapi_document)
            if api_app is not None and api_app.openapi_document is not None
            else None
        ),
        display_name=integration.name,
        in_code_tool_id=None,
        custom_headers=[
            {"key": name, "value": mask_string(value)}
            for name, value in _stored_headers(integration, organization).items()
        ],
        passthrough_auth=integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN,
        mcp_server_id=tool.mcp_server_id,
        user_id=(
            str(integration.owner_user_id)
            if integration.owner_user_id is not None
            else None
        ),
        oauth_config_id=None,
        oauth_config_name=None,
        enabled=integration.enabled,
        default_chat_enabled=integration.installation_policy in _DEFAULT_CHAT_POLICIES,
        integration_id=integration.id,
    )


def _openapi_tool_or_404(
    tool_id: int, db_session: Session
) -> tuple[Tool, Integration, IntegrationConnection | None]:
    row = get_openapi_tool_with_integration(tool_id, db_session)
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Tool with ID {tool_id} not found")
    return row


def openapi_tool_snapshot(
    tool: Tool, integration: Integration, db_session: Session
) -> ToolSnapshot:
    return openapi_tool_snapshots([(tool, integration)], db_session)[0]


def openapi_tool_snapshots(
    tools: Sequence[tuple[Tool, Integration]], db_session: Session
) -> list[ToolSnapshot]:
    integration_ids = [integration.id for _, integration in tools]
    connections = list_connections(db_session, integration_ids, None)
    api_apps = list_api_apps_by_integration(integration_ids, db_session)
    return [
        _alias_snapshot(
            tool,
            integration,
            connections.get((integration.id, None)),
            api_apps.get(integration.id),
        )
        for tool, integration in tools
    ]


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
            config=OpenApiConfigInput(
                openapi_document=json.dumps(tool_data.definition)
            ),
        ),
        db_session,
    )
    _save_organization_fields(integration, auth.organization_fields, db_session)
    _set_default_chat(integration, tool_data.default_chat_enabled, db_session)
    db_session.commit()
    tool = get_openapi_tool_for_integration(integration.id, db_session)
    if tool is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The OpenAPI schema is missing.")
    return openapi_tool_snapshot(tool, integration, db_session)


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
    tool, integration, organization = _openapi_tool_or_404(tool_id, db_session)
    # Check before the stored headers are read; the update locks the row.
    get_manageable_integration(user, integration.id, db_session)

    update = IntegrationUpdate()
    if tool_data.name is not None:
        update.name = tool_data.name
    if tool_data.description is not None:
        update.description = tool_data.description
    if tool_data.definition is not None:
        update.config = OpenApiConfigInput(
            openapi_document=json.dumps(tool_data.definition)
        )

    organization_fields: dict[str, str] = {}
    if tool_data.custom_headers is not None or tool_data.passthrough_auth is not None:
        stored = _stored_headers(integration, organization)
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
        if integration.auth_method is IntegrationAuthMethod.OAUTH2:
            # The old fields cannot express OAuth sign-in, so the values that
            # the read returned keep it, and any other value is refused.
            if passthrough or {h.key: h.value for h in headers} != stored:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "This tool signs in with OAuth. Change its sign-in on the "
                    "integration (/admin/integrations).",
                )
        else:
            auth = _auth_settings(headers, passthrough)
            update.auth_mode = auth.auth_mode
            update.auth_method = auth.auth_method
            update.header_template = auth.header_template
            update.credential_fields = auth.credential_fields
            organization_fields = auth.organization_fields

    integration = update_integration__no_commit(
        user, integration.id, update, db_session
    )
    if (
        organization_fields
        != _organization_secret(get_connection(db_session, integration.id, None)).fields
    ):
        _save_organization_fields(integration, organization_fields, db_session)
    _set_default_chat(integration, tool_data.default_chat_enabled, db_session)
    db_session.commit()
    return openapi_tool_snapshot(tool, integration, db_session)


@admin_router.delete("/custom/{tool_id}", tags=PUBLIC_API_TAGS)
def delete_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> None:
    _, integration, _ = _openapi_tool_or_404(tool_id, db_session)
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
    user: User,
    tools: Sequence[tuple[Tool, Integration, IntegrationConnection | None]],
    db_session: Session,
    *,
    include_managed: bool,
) -> list[ToolSnapshot]:
    states = {
        state.integration_id: state
        for state in load_user_integration_states([user.id], db_session)
    }
    api_apps = list_api_apps_by_integration(
        [integration.id for _, integration, _ in tools], db_session
    )
    snapshots: list[ToolSnapshot] = []
    for tool, integration, organization in tools:
        state = states.get(integration.id)
        can_manage = manages_integration(user, integration)
        if state is None and not (include_managed and can_manage):
            continue
        if not include_managed and not integration.enabled:
            continue
        if tool.mcp_server_id is not None:
            snapshot = ToolSnapshot.from_model(tool, integration_id=integration.id)
        else:
            snapshot = _alias_snapshot(
                tool, integration, organization, api_apps.get(integration.id)
            )
        snapshot.user_enabled_in_chat = state.turned_on if state is not None else True
        snapshot.default_chat_enabled = (
            integration.installation_policy in _DEFAULT_CHAT_POLICIES
        )
        if include_managed:
            snapshot.permissions = tool_permissions(can_manage=can_manage)
        snapshots.append(snapshot)
    return snapshots


@router.get("/openapi", tags=PUBLIC_API_TAGS)
def list_openapi_tools(
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    return _openapi_snapshots(
        user,
        list_openapi_tools_with_integration(db_session),
        db_session,
        include_managed=True,
    )


@router.get("/{tool_id}", tags=PUBLIC_API_TAGS)
def get_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ToolSnapshot:
    tools = get_tools_by_ids([tool_id], db_session)
    if tools and tools[0].in_code_tool_id is not None:
        return ToolSnapshot.from_model(tools[0])
    row = get_openapi_tool_with_integration(
        tool_id, db_session
    ) or get_mcp_tool_with_integration(tool_id, db_session)
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Tool with ID {tool_id} not found")
    snapshots = _openapi_snapshots(
        user,
        [row],
        db_session,
        include_managed=True,
    )
    if snapshots:
        snapshots[0].permissions = {}
        return snapshots[0]
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You can only view actions you manage, or ones you have access to.",
    )


@router.patch("/{tool_id}/preferences", tags=PUBLIC_API_TAGS)
def update_tool_user_preferences(
    tool_id: int,
    request: ToolUserPreferences,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ToolUserPreferences:
    """Turn the integration of the custom tool on or off for the user."""
    tools = get_tools_by_ids([tool_id], db_session)
    if tools and (
        tools[0].in_code_tool_id is not None or tools[0].mcp_server_id is not None
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only OpenAPI plugins support these preferences",
        )
    _, integration, _ = _openapi_tool_or_404(tool_id, db_session)
    if not load_user_integration_states([user.id], db_session, [integration.id]):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "Plugin is not available"
        )
    set_integration_preferences__no_commit(
        user.id, [integration.id], request.enabled_in_chat, db_session
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
    return built_in + _openapi_snapshots(
        user,
        list_openapi_tools_with_integration(db_session)
        + list_mcp_tools_with_integration(db_session),
        db_session,
        include_managed=False,
    )
