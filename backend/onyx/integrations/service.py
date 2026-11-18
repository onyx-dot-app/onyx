"""The logic of the integration API: who manages an integration, create,
update and delete, the views, the action policies and the connections."""

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.db.enums import (
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MCPTransport,
    Permission,
    PermissionAuthority,
)
from onyx.db.external_app import associate_built_in_skill__no_commit
from onyx.db.integration import (
    count_integration_actions,
    create_external_app_row__no_commit,
    create_mcp_server_row__no_commit,
    create_openapi_tool_row__no_commit,
    delete_integration__no_commit,
    delete_oauth_client__no_commit,
    get_external_app_for_integration,
    get_integration_by_id,
    get_mcp_server_for_integration,
    get_openapi_tool_for_integration,
    insert_integration__no_commit,
    list_action_summaries,
    list_external_apps_by_integration,
    list_integration_actions,
    list_integration_ids_held_by_plugins,
    list_integration_plugin_rows,
    list_integrations,
    list_integrations_by_ids,
    list_mcp_servers_by_integration,
    lock_integration,
    lock_integration__no_commit,
    rename_kind_row__no_commit,
    replace_integration_actions__no_commit,
    set_policy_rows__no_commit,
    upsert_oauth_client__no_commit,
)
from onyx.db.integration_connection import (
    get_oauth_client,
    get_oauth_clients,
    list_connections,
    user_can_see_integration,
)
from onyx.db.integration_policy import get_policy_rows, list_admin_policy_rows
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationAction,
    IntegrationOAuthClient,
    User,
)
from onyx.db.plugin import (
    create_integration_plugin__no_commit,
    set_plugin_preferences__no_commit,
)
from onyx.db.plugin_access import (
    UserPluginState,
    affected_user_ids_for_plugins,
    get_visible_plugin_ids,
    load_user_plugin_states,
    visible_plugin_ids,
)
from onyx.db.users import fetch_users_by_ids
from onyx.db.utils import UNSET
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import get_onyx_managed_provider
from onyx.external_apps.url_glob import UrlGlob
from onyx.integrations.connection_models import (
    SIGN_IN_SETTINGS_CHANGED_REASON,
    ConnectionState,
    read_connection_secret,
    read_oauth_client,
)
from onyx.integrations.connections import (
    IntegrationStatus,
    MissingHeaderValueError,
    credential_field_keys,
    has_placeholder,
    header_field_keys,
    header_template_missing,
    integration_statuses,
    mark_sign_in_settings_changed,
    oauth_client_configured,
    render_headers,
    sign_in_host,
    sign_in_settings_for,
)
from onyx.integrations.craft import always_asks, craft_service_urls
from onyx.integrations.kinds.mcp_server import fetch_mcp_actions, mcp_action_specs
from onyx.integrations.models import (
    EffectivePolicy,
    IntegrationActionSpec,
    IntegrationPluginRow,
)
from onyx.integrations.policy import (
    DEFAULT_ACTION_KEY,
    STORED_TO_EFFECTIVE,
    action_default_policy,
    admin_policy,
)
from onyx.integrations.presets import PRESETS, Preset, get_preset
from onyx.integrations.sync import sync_integration_actions__no_commit
from onyx.server.features.build.utils import is_craft_available_for_deployment
from onyx.server.features.integrations.models import (
    ActionGrantsResponse,
    AdminIntegration,
    AdminIntegrationDetail,
    AgentIntegrationOption,
    AgentPluginOption,
    CredentialField,
    CustomConfigInput,
    IntegrationActionsResponse,
    IntegrationActionsUpdate,
    IntegrationActionView,
    IntegrationConfigInput,
    IntegrationConfigView,
    IntegrationCreate,
    IntegrationPluginRef,
    IntegrationShape,
    IntegrationUpdate,
    McpServerConfigInput,
    MemberAction,
    MemberIntegration,
    MemberIntegrationDetail,
    MemberPluginRef,
    OAuthClientInput,
    OAuthClientView,
    OpenApiConfigInput,
    PresetConfigInput,
    PresetConfigView,
    PresetView,
)
from onyx.server.features.mcp.client import discover_mcp_tools
from onyx.server.features.mcp.ssrf import validate_mcp_url
from onyx.tools.tool_implementations.custom.custom_tool import validate_custom_tool_url
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_url,
    validate_openapi_schema,
)
from onyx.utils.encryption import is_masked_credential, mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

_CLIENT_CREDENTIAL_KEYS = ("client_id", "client_secret")

# The fields of an update that Onyx owns for an Onyx-managed preset.
_ONYX_MANAGED_FIELDS = frozenset(
    {
        "auth_mode",
        "auth_method",
        "credential_fields",
        "header_template",
        "oauth_client",
        "config",
    }
)
_TOKEN_METHODS = frozenset(
    {
        IntegrationAuthMethod.OAUTH2,
        IntegrationAuthMethod.API_KEY,
        IntegrationAuthMethod.ONYX_LOGIN,
    }
)


def manages_integration(user: User, plugins: Collection[IntegrationPluginRow]) -> bool:
    """A scoped manager manages it only when each holding plugin is in its
    own My uploads."""
    authority = has_permission(user, Permission.MANAGE_ACTIONS)
    if authority is PermissionAuthority.GLOBAL:
        return True
    if authority is PermissionAuthority.NONE or not plugins:
        return False
    return all(
        not plugin.in_organization_library and plugin.author_user_id == user.id
        for plugin in plugins
    )


def _integration_or_404(
    integration_id: int, db_session: Session, *, lock: bool = False
) -> Integration:
    integration = (
        lock_integration(integration_id, db_session)
        if lock
        else get_integration_by_id(integration_id, db_session)
    )
    if integration is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")
    return integration


def get_viewable_integration(
    user: User, integration_id: int, db_session: Session
) -> Integration:
    integration = _integration_or_404(integration_id, db_session)
    plugins = list_integration_plugin_rows([integration.id], db_session)[integration.id]
    if not (
        manages_integration(user, plugins)
        or user_can_see_integration(db_session, integration.id, user.id)
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")
    return integration


def get_manageable_integration(
    user: User, integration_id: int, db_session: Session, *, lock: bool = False
) -> Integration:
    integration = _integration_or_404(integration_id, db_session, lock=lock)
    plugins = list_integration_plugin_rows([integration.id], db_session)[integration.id]
    if manages_integration(user, plugins):
        return integration
    if user_can_see_integration(db_session, integration.id, user.id):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide action manager can change this integration.",
        )
    raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")


def _check_onyx_login(user: User, method: IntegrationAuthMethod | None) -> None:
    if method is IntegrationAuthMethod.ONYX_LOGIN and not has_global_permission(
        user, Permission.MANAGE_ACTIONS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide action manager can send users' Onyx login "
            "to an integration.",
        )


def _external_apps(
    integrations: Collection[Integration], db_session: Session
) -> dict[int, ExternalApp]:
    return list_external_apps_by_integration(
        [
            integration.id
            for integration in integrations
            if integration.external_app_id is not None
        ],
        db_session,
    )


def _shapes(
    integrations: Collection[Integration], external_apps: Mapping[int, ExternalApp]
) -> dict[int, tuple[IntegrationShape, str | None]]:
    """The shape and the preset id of each integration."""
    shapes: dict[int, tuple[IntegrationShape, str | None]] = {}
    for integration in integrations:
        if integration.kind is IntegrationKind.MCP:
            shapes[integration.id] = (IntegrationShape.MCP_SERVER, None)
            continue
        if integration.tool_id is not None:
            shapes[integration.id] = (IntegrationShape.OPENAPI, None)
            continue
        app = external_apps.get(integration.id)
        if app is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"Integration {integration.id} has no API settings.",
            )
        shapes[integration.id] = (
            (IntegrationShape.CUSTOM, None)
            if app.app_type == ExternalAppType.CUSTOM
            else (IntegrationShape.PRESET, app.app_type.value)
        )
    return shapes


def _shape_and_preset(
    integration: Integration, db_session: Session
) -> tuple[IntegrationShape, str | None]:
    return _shapes([integration], _external_apps([integration], db_session))[
        integration.id
    ]


def _preset_or_400(preset_id: str) -> Preset:
    try:
        app_type = ExternalAppType(preset_id)
    except ValueError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Unknown preset '{preset_id}'."
        ) from error
    preset = get_preset(app_type)
    if preset is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"Unknown preset '{preset_id}'.")
    return preset


def _is_onyx_managed(preset: Preset | None) -> bool:
    """On Cloud, Onyx provides the OAuth client and settings of some presets."""
    return (
        MULTI_TENANT
        and preset is not None
        and get_onyx_managed_provider(preset.app_type) is not None
    )


def _refuse_onyx_managed(preset: Preset | None, action: str) -> None:
    if _is_onyx_managed(preset):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Onyx provides this app. You cannot {action} it.",
        )


def _preset_methods(preset: Preset) -> list[IntegrationAuthMethod | None]:
    if isinstance(preset.provider, OAuthExternalAppProvider):
        return [IntegrationAuthMethod.OAUTH2]
    if preset.provider.spec.descriptor.auth_template:
        return [IntegrationAuthMethod.API_KEY]
    return [None]


def preset_views(user: User) -> list[PresetView]:
    """The presets an admin can add. Empty when Craft is not available:
    only Craft runs a preset app."""
    if not is_craft_available_for_deployment(user):
        return []
    return [
        PresetView(
            id=preset.id,
            name=preset.name,
            auth_methods=_preset_methods(preset),
            required_org_credential_fields=[
                CredentialField(key=field.key, label=field.label, secret=field.secret)
                for field in preset.provider.spec.descriptor.required_org_credential_fields
            ],
            setup_instructions=preset.provider.spec.descriptor.setup_instructions
            or None,
        )
        for preset in sorted(PRESETS.values(), key=lambda preset: preset.name)
        if not _is_onyx_managed(preset)
    ]


def _allowed_methods(
    shape: IntegrationShape, preset: Preset | None
) -> list[IntegrationAuthMethod | None]:
    if shape is IntegrationShape.PRESET and preset is not None:
        return _preset_methods(preset)
    if shape is IntegrationShape.CUSTOM:
        return [IntegrationAuthMethod.API_KEY]
    return list(_TOKEN_METHODS)


def validate_openapi_definition(definition: dict[str, Any]) -> None:
    try:
        validate_openapi_schema(definition)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e
    server_url = openapi_to_url(definition)
    try:
        # No DNS at save time; each call resolves and checks again.
        validate_custom_tool_url(server_url, resolve_dns=False)
    except (SSRFException, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Server URL '{server_url}' is not allowed: {e}",
        ) from e


def _validate_url_patterns(patterns: list[str]) -> None:
    if not patterns:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Add at least one URL pattern.")
    for pattern in patterns:
        try:
            UrlGlob.parse(pattern)
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error


def _credential_fields_json(
    fields: list[CredentialField] | None,
    header_template: Mapping[str, str] | None,
    stored: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    if fields is not None:
        return [field.model_dump() for field in fields]
    if not header_template:
        return None
    kept = {field.get("key"): field for field in stored or []}
    return [
        kept.get(key) or {"key": key, "label": key.replace("_", " "), "secret": True}
        for key in header_field_keys(header_template)
    ] or None


def _validate_sign_in(
    *,
    shape: IntegrationShape,
    preset: Preset | None,
    auth_mode: IntegrationAuthMode,
    auth_method: IntegrationAuthMethod | None,
    header_template: Mapping[str, str] | None,
    oauth_client: OAuthClientInput | None,
    has_stored_client: bool,
) -> None:
    if auth_mode is IntegrationAuthMode.NONE:
        if auth_method is not None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "An integration with no sign-in has no sign-in method.",
            )
        return
    if auth_method is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Pick a sign-in method.")
    if auth_method not in _allowed_methods(shape, preset):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"This integration cannot sign in with {auth_method.value}.",
        )
    if (
        auth_method is IntegrationAuthMethod.ONYX_LOGIN
        and auth_mode is not IntegrationAuthMode.INDIVIDUAL
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The Onyx login sign-in needs a connection for each user.",
        )
    if (
        auth_method is IntegrationAuthMethod.API_KEY
        and shape is not IntegrationShape.PRESET
        and not (header_template and header_field_keys(header_template))
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "An API key sign-in needs a header with a {placeholder}.",
        )
    if auth_method is not IntegrationAuthMethod.OAUTH2:
        return
    if oauth_client is None:
        if has_stored_client:
            return
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Add the OAuth client settings.")
    mode = oauth_client.provider_mode
    if (mode is IntegrationOAuthProviderMode.PRESET) != (
        shape is IntegrationShape.PRESET
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only a preset uses the preset OAuth settings.",
        )
    if (
        mode is IntegrationOAuthProviderMode.DISCOVERY
        and shape is not IntegrationShape.MCP_SERVER
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only an MCP server can discover its OAuth settings.",
        )
    if mode is IntegrationOAuthProviderMode.MANUAL:
        if not oauth_client.authorization_url or not oauth_client.token_url:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Add the authorization URL and the token URL.",
            )
        validate_mcp_url(
            oauth_client.authorization_url, "authorization_url", require_https=True
        )
        validate_mcp_url(oauth_client.token_url, "token_url", require_https=True)


def _write_oauth_client(
    integration: Integration,
    oauth_client: OAuthClientInput,
    shape: IntegrationShape,
    org_credentials: Mapping[str, str],
    *,
    keep_secret: bool,
    db_session: Session,
) -> None:
    preset_mode = shape is IntegrationShape.PRESET
    client_secret = oauth_client.client_secret or org_credentials.get("client_secret")
    additional_params = oauth_client.additional_params
    if preset_mode:
        # A preset keeps its host settings here (``preset_host_values``).
        stored = get_oauth_client(db_session, integration.id)
        additional_params = (
            _host_values(org_credentials)
            if org_credentials
            else (read_oauth_client(stored).host_values if stored is not None else None)
        )
    upsert_oauth_client__no_commit(
        integration_id=integration.id,
        provider_mode=oauth_client.provider_mode,
        authorization_url=None
        if preset_mode
        else oauth_client.authorization_url or None,
        token_url=None if preset_mode else oauth_client.token_url or None,
        scopes=oauth_client.scopes,
        additional_params=additional_params,
        pkce=oauth_client.pkce,
        client_id=oauth_client.client_id or org_credentials.get("client_id") or None,
        client_secret=(UNSET if keep_secret and not client_secret else client_secret),
        db_session=db_session,
    )


def _preset_org_credentials(
    preset: Preset, organization_credentials: Mapping[str, str] | None
) -> dict[str, str]:
    values = {
        key: value.strip()
        for key, value in (organization_credentials or {}).items()
        if value.strip()
    }
    missing = [
        field.label
        for field in preset.provider.spec.descriptor.required_org_credential_fields
        if field.key not in values
    ]
    if missing:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Fill in: " + ", ".join(missing))
    return values


def _host_values(org_credentials: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in org_credentials.items()
        if key not in _CLIENT_CREDENTIAL_KEYS
    }


def _mcp_target(
    integration_id: int, db_session: Session
) -> tuple[str, MCPTransport | None, dict[str, str] | None] | None:
    server = get_mcp_server_for_integration(integration_id, db_session)
    integration = get_integration_by_id(integration_id, db_session)
    if server is None or integration is None:
        return None
    return server.server_url, server.transport, integration.header_template


@contextmanager
def _reaching(name: str) -> Iterator[None]:
    """An error that is not an ``OnyxError`` becomes a 502."""
    try:
        yield
    except OnyxError:
        raise
    except Exception as error:
        logger.exception("Could not reach %s", name)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY, f"Could not reach {name}."
        ) from error


def _discover_new_server(
    name: str,
    config: McpServerConfigInput,
    header_template: Mapping[str, str] | None,
    user: User,
) -> list[IntegrationActionSpec]:
    """The tools of an MCP server with no sign-in, before anything is saved."""
    try:
        headers = render_headers(
            header_template, None, extra_values={"user_email": user.email}
        )
    except MissingHeaderValueError as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, error.detail) from error
    with _reaching(name):
        tools = discover_mcp_tools(
            config.server_url, headers, transport=config.transport
        )
    return mcp_action_specs(tools)


def _discover_and_sync(
    integration: Integration, user: User, db_session: Session
) -> None:
    if integration.kind is IntegrationKind.MCP:
        # Discovery calls the server, so it runs before the lock. Under the
        # lock, an update that changed the server meanwhile refuses the result.
        integration_id = integration.id
        target = _mcp_target(integration_id, db_session)
        actions = fetch_mcp_actions(integration, user, db_session)
        lock_integration__no_commit(integration_id, db_session)
        if _mcp_target(integration_id, db_session) != target:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "The server settings changed while Onyx loaded the actions. "
                "Refresh the actions again.",
            )
        replace_integration_actions__no_commit(
            integration_id, IntegrationActionSource.MCP, actions, db_session
        )
        return
    sync_integration_actions__no_commit(integration, db_session)


def create_integration__no_commit(
    user: User,
    request: IntegrationCreate,
    db_session: Session,
    *,
    save_unreachable_server: bool = False,
) -> Integration:
    """Make the integration, its kind row, its OAuth client, one plugin that
    holds it, and its actions. The caller commits; an error leaves nothing.
    With ``save_unreachable_server``, an MCP server with no sign-in that
    cannot be reached is saved with no actions until a refresh."""
    if request.for_organization and not has_global_permission(
        user, Permission.MANAGE_ACTIONS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide action manager can add an integration "
            "for the organization.",
        )
    name = request.name.strip()
    if not name:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Give the integration a name.")
    config = request.config
    shape = IntegrationShape(config.shape)
    if shape in (
        IntegrationShape.PRESET,
        IntegrationShape.CUSTOM,
    ) and not is_craft_available_for_deployment(user):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Craft is not available, so you cannot add an external app.",
        )
    preset = (
        _preset_or_400(config.preset_id)
        if isinstance(config, PresetConfigInput)
        else None
    )
    _refuse_onyx_managed(preset, "add")
    auth_method = (
        None if request.auth_mode is IntegrationAuthMode.NONE else request.auth_method
    )
    header_template = request.header_template
    if (
        preset is not None
        and header_template is None
        and auth_method is IntegrationAuthMethod.API_KEY
    ):
        header_template = dict(preset.provider.spec.descriptor.auth_template)
    _check_onyx_login(user, auth_method)
    _validate_sign_in(
        shape=shape,
        preset=preset,
        auth_mode=request.auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        oauth_client=request.oauth_client,
        has_stored_client=False,
    )
    org_credentials = (
        _preset_org_credentials(preset, config.organization_credentials)
        if preset is not None and isinstance(config, PresetConfigInput)
        else {}
    )
    if isinstance(config, McpServerConfigInput):
        validate_mcp_url(config.server_url, "server_url", require_https=False)
    elif isinstance(config, OpenApiConfigInput):
        validate_openapi_definition(config.openapi_spec)
    elif isinstance(config, CustomConfigInput):
        _validate_url_patterns(config.upstream_url_patterns)
    mcp_actions: list[IntegrationActionSpec] | None = None
    if (
        isinstance(config, McpServerConfigInput)
        and request.auth_mode is IntegrationAuthMode.NONE
    ):
        try:
            mcp_actions = _discover_new_server(name, config, header_template, user)
        except OnyxError as error:
            if (
                not save_unreachable_server
                or error.error_code is not OnyxErrorCode.BAD_GATEWAY
            ):
                raise
            logger.warning(
                "Saving MCP integration %s with no actions: %s", name, error.detail
            )

    mcp_server_id: int | None = None
    tool_id: int | None = None
    external_app_id: int | None = None
    if isinstance(config, McpServerConfigInput):
        mcp_server_id = create_mcp_server_row__no_commit(
            name=name,
            description=request.description,
            owner_email=user.email,
            server_url=config.server_url,
            transport=config.transport,
            db_session=db_session,
        ).id
    elif isinstance(config, OpenApiConfigInput):
        tool_id = create_openapi_tool_row__no_commit(
            name=name,
            description=request.description,
            user_id=user.id,
            openapi_spec=config.openapi_spec,
            db_session=db_session,
        ).id
    elif preset is not None:
        app = create_external_app_row__no_commit(
            name=name,
            app_type=preset.app_type,
            upstream_url_patterns=preset.provider.resolve_upstream_url_patterns(
                _host_values(org_credentials),
                list(preset.provider.spec.descriptor.upstream_url_patterns),
            ),
            auth_template=dict(preset.provider.spec.descriptor.auth_template),
            db_session=db_session,
        )
        associate_built_in_skill__no_commit(db_session, app)
        external_app_id = app.id
    elif isinstance(config, CustomConfigInput):
        external_app_id = create_external_app_row__no_commit(
            name=name,
            app_type=ExternalAppType.CUSTOM,
            upstream_url_patterns=config.upstream_url_patterns,
            auth_template=dict(header_template or {}),
            db_session=db_session,
        ).id
    integration = insert_integration__no_commit(
        name=name,
        description=request.description,
        created_by_user_id=user.id,
        auth_mode=request.auth_mode,
        auth_method=auth_method,
        credential_fields=(
            _credential_fields_json(request.credential_fields, header_template)
            if auth_method is IntegrationAuthMethod.API_KEY
            else None
        ),
        header_template=header_template,
        mcp_server_id=mcp_server_id,
        external_app_id=external_app_id,
        tool_id=tool_id,
        db_session=db_session,
    )

    if auth_method is IntegrationAuthMethod.OAUTH2 and request.oauth_client:
        _write_oauth_client(
            integration,
            request.oauth_client,
            shape,
            org_credentials,
            keep_secret=False,
            db_session=db_session,
        )

    plugin = create_integration_plugin__no_commit(
        integration_id=integration.id,
        name=name,
        description=request.description or "",
        author=user,
        for_organization=request.for_organization,
        db_session=db_session,
    )
    if not request.for_organization:
        set_plugin_preferences__no_commit(user.id, [plugin.id], True, db_session)

    if mcp_actions is not None:
        replace_integration_actions__no_commit(
            integration.id, IntegrationActionSource.MCP, mcp_actions, db_session
        )
    elif shape is not IntegrationShape.MCP_SERVER:
        sync_integration_actions__no_commit(integration, db_session)
    return integration


def _apply_config(
    integration: Integration,
    shape: IntegrationShape,
    config: IntegrationConfigInput,
    oauth_client: OAuthClientInput | None,
    db_session: Session,
) -> bool:
    """Write the kind settings of an update. Returns whether the actions
    need a sync."""
    if IntegrationShape(config.shape) is not shape:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "The kind of an integration cannot change."
        )
    if isinstance(config, McpServerConfigInput):
        validate_mcp_url(config.server_url, "server_url", require_https=False)
        server = get_mcp_server_for_integration(integration.id, db_session)
        if server is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The MCP server is missing.")
        server.server_url = config.server_url
        server.transport = config.transport
        return False
    if isinstance(config, OpenApiConfigInput):
        validate_openapi_definition(config.openapi_spec)
        tool = get_openapi_tool_for_integration(integration.id, db_session)
        if tool is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The OpenAPI schema is missing.")
        tool.openapi_schema = config.openapi_spec
        return True
    app = get_external_app_for_integration(integration.id, db_session)
    if app is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The app settings are missing.")
    if isinstance(config, PresetConfigInput):
        preset = _preset_or_400(config.preset_id)
        if preset.app_type != app.app_type:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "The preset of an integration cannot change.",
            )
        if config.organization_credentials is not None:
            org_credentials = _preset_org_credentials(
                preset, config.organization_credentials
            )
            app.upstream_url_patterns = preset.provider.resolve_upstream_url_patterns(
                _host_values(org_credentials),
                list(preset.provider.spec.descriptor.upstream_url_patterns),
            )
            if integration.auth_method is IntegrationAuthMethod.OAUTH2:
                _write_oauth_client(
                    integration,
                    oauth_client
                    or OAuthClientInput(
                        provider_mode=IntegrationOAuthProviderMode.PRESET
                    ),
                    shape,
                    org_credentials,
                    keep_secret=True,
                    db_session=db_session,
                )
        return False
    _validate_url_patterns(config.upstream_url_patterns)
    app.upstream_url_patterns = config.upstream_url_patterns
    return False


def _updated_header_template(
    integration: Integration,
    request: IntegrationUpdate,
    auth_method: IntegrationAuthMethod | None,
) -> dict[str, str] | None:
    if "header_template" in request.model_fields_set:
        return (
            keep_masked_values(
                request.header_template, integration.header_template or {}
            )
            if request.header_template is not None
            else None
        )
    if (
        integration.auth_method is IntegrationAuthMethod.API_KEY
        and auth_method is not IntegrationAuthMethod.API_KEY
    ):
        # The API key placeholders cannot be filled with another method.
        return None
    return integration.header_template


def update_integration__no_commit(
    user: User,
    integration_id: int,
    request: IntegrationUpdate,
    db_session: Session,
) -> Integration:
    """Apply a partial update. A change of the sign-in settings sets each
    connection to Needs reconnect; a change of only the client secret does
    not. The caller commits."""
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    fields = request.model_fields_set
    shape, preset_id = _shape_and_preset(integration, db_session)
    preset = _preset_or_400(preset_id) if preset_id is not None else None
    if _is_onyx_managed(preset) and fields & _ONYX_MANAGED_FIELDS:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Onyx provides the sign-in and settings of this app. You can change "
            "its name, description, switch and Always allow setting.",
        )
    stored_client = get_oauth_client(db_session, integration.id, for_update=True)
    before = sign_in_settings_for(
        integration, stored_client, sign_in_host(integration, db_session)
    )
    fields_before = set(credential_field_keys(integration))

    if "name" in fields and request.name is not None:
        name = request.name.strip()
        if not name:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Give the integration a name.")
        integration.name = name
        rename_kind_row__no_commit(integration, name, db_session)
    if "description" in fields:
        integration.description = request.description
    if "enabled" in fields and request.enabled is not None:
        integration.enabled = request.enabled
    if (
        "users_can_save_always_allow" in fields
        and request.users_can_save_always_allow is not None
    ):
        integration.users_can_save_always_allow = request.users_can_save_always_allow

    auth_mode = (
        request.auth_mode
        if "auth_mode" in fields and request.auth_mode is not None
        else integration.auth_mode
    )
    auth_method = (
        request.auth_method if "auth_method" in fields else integration.auth_method
    )
    if auth_mode is IntegrationAuthMode.NONE:
        auth_method = None
    header_template = _updated_header_template(integration, request, auth_method)
    header_template_changed = header_template != integration.header_template
    if auth_method is not integration.auth_method or fields & {
        "config",
        "header_template",
    }:
        _check_onyx_login(user, auth_method)
    _validate_sign_in(
        shape=shape,
        preset=preset,
        auth_mode=auth_mode,
        auth_method=auth_method,
        header_template=header_template,
        oauth_client=request.oauth_client if "oauth_client" in fields else None,
        has_stored_client=stored_client is not None,
    )
    integration.auth_mode = auth_mode
    integration.auth_method = auth_method
    integration.header_template = header_template
    if auth_method is not IntegrationAuthMethod.API_KEY:
        integration.credential_fields = None
    elif "credential_fields" in fields or "header_template" in fields:
        integration.credential_fields = _credential_fields_json(
            request.credential_fields,
            header_template,
            None if "credential_fields" in fields else integration.credential_fields,
        )

    if auth_method is not IntegrationAuthMethod.OAUTH2:
        if stored_client is not None:
            delete_oauth_client__no_commit(integration.id, db_session)
    elif "oauth_client" in fields and request.oauth_client is not None:
        _write_oauth_client(
            integration,
            request.oauth_client,
            shape,
            {},
            keep_secret=True,
            db_session=db_session,
        )

    needs_sync = False
    if "config" in fields and request.config is not None:
        needs_sync = _apply_config(
            integration, shape, request.config, request.oauth_client, db_session
        )
    if shape is IntegrationShape.CUSTOM and header_template_changed:
        app = get_external_app_for_integration(integration.id, db_session)
        if app is not None:
            app.auth_template = dict(header_template or {})
    db_session.flush()

    after = sign_in_settings_for(
        integration,
        get_oauth_client(db_session, integration.id),
        sign_in_host(integration, db_session),
    )
    # A new field leaves each saved connection without a value for it.
    if before != after or not set(credential_field_keys(integration)) <= fields_before:
        mark_sign_in_settings_changed(integration.id, db_session)
    if needs_sync:
        sync_integration_actions__no_commit(integration, db_session)
    return integration


def delete_integration_for_user__no_commit(
    user: User, integration_id: int, db_session: Session
) -> None:
    integration = get_manageable_integration(
        user, integration_id, db_session, lock=True
    )
    _, preset_id = _shape_and_preset(integration, db_session)
    _refuse_onyx_managed(
        _preset_or_400(preset_id) if preset_id is not None else None, "delete"
    )
    delete_integration__no_commit(integration, db_session)


def _plugin_ref(row: IntegrationPluginRow) -> IntegrationPluginRef:
    return IntegrationPluginRef(
        plugin_id=row.plugin_id,
        plugin_name=row.plugin_name,
        scope="organization" if row.in_organization_library else "personal",
        owner_email=row.owner_email,
        installation_policy=row.installation_policy,
    )


def _credential_fields(integration: Integration) -> list[CredentialField]:
    stored: dict[str, dict[str, Any]] = {
        str(field.get("key")): field for field in integration.credential_fields or []
    }
    fields: list[CredentialField] = []
    for key in credential_field_keys(integration):
        field = stored.get(key, {})
        fields.append(
            CredentialField(
                key=key,
                label=str(field.get("label") or key.replace("_", " ")),
                secret=bool(field.get("secret", True)),
            )
        )
    return fields


def _action_views(
    integration: Integration,
    actions: list[IntegrationAction],
    admin_rows: Mapping[str, IntegrationActionPolicyValue],
) -> list[IntegrationActionView]:
    return [
        IntegrationActionView(
            key=action.key,
            display_name=action.display_name,
            description=action.description,
            read_only=action.read_only,
            default_policy=action_default_policy(action),
            admin_policy=(
                STORED_TO_EFFECTIVE[admin_rows[action.key]]
                if action.key in admin_rows
                else None
            ),
            effective_admin_policy=admin_policy(admin_rows, action.key, action),
            always_asks=always_asks(integration.kind, action.key),
        )
        for action in actions
    ]


def action_views(
    integration: Integration, db_session: Session
) -> list[IntegrationActionView]:
    rows = get_policy_rows(db_session, integration.id, None)
    return _action_views(
        integration, list_integration_actions(integration.id, db_session), rows.admin
    )


def _setup_reason(
    integration: Integration, oauth_client: IntegrationOAuthClient | None
) -> str:
    if header_template_missing(integration):
        return "Add the header template."
    if not oauth_client_configured(integration, oauth_client):
        return "Add the OAuth client ID."
    return "Connect the account of the organization."


_SIGN_IN_CHANGED_ADMIN_REASON = (
    "The sign-in settings changed. Connect the account of the organization again."
)


def _organization_statuses(
    integrations: Collection[Integration], db_session: Session
) -> dict[int, IntegrationStatus]:
    """The status of each organization connection, with a reason that tells
    the admin what to do."""
    # The old organization row of an integration with no template may not
    # read, so its status is not resolved.
    statuses = integration_statuses(
        [
            integration
            for integration in integrations
            if not header_template_missing(integration)
        ],
        None,
        db_session,
    )
    for integration_id, status in statuses.items():
        if status.reason == SIGN_IN_SETTINGS_CHANGED_REASON:
            statuses[integration_id] = status.model_copy(
                update={"reason": _SIGN_IN_CHANGED_ADMIN_REASON}
            )
    for integration in integrations:
        if header_template_missing(integration):
            statuses[integration.id] = IntegrationStatus(
                state=ConnectionState.NOT_SET_UP,
                reason=None,
            )
    not_set_up = [
        integration
        for integration in integrations
        if statuses[integration.id].state is ConnectionState.NOT_SET_UP
    ]
    oauth_clients = get_oauth_clients(
        db_session, [integration.id for integration in not_set_up]
    )
    for integration in not_set_up:
        statuses[integration.id] = statuses[integration.id].model_copy(
            update={
                "reason": _setup_reason(integration, oauth_clients.get(integration.id))
            }
        )
    return statuses


def organization_status(
    integration: Integration, db_session: Session
) -> IntegrationStatus:
    return _organization_statuses([integration], db_session)[integration.id]


def _creator_emails(
    integrations: Collection[Integration], db_session: Session
) -> dict[UUID, str]:
    creator_ids = {
        integration.created_by_user_id
        for integration in integrations
        if integration.created_by_user_id is not None
    }
    return {
        creator.id: creator.email
        for creator in fetch_users_by_ids(db_session, list(creator_ids))
    }


def _admin_views(
    user: User,
    integrations: Collection[Integration],
    plugin_rows: Mapping[int, list[IntegrationPluginRow]],
    db_session: Session,
) -> list[AdminIntegration]:
    creator_emails = _creator_emails(integrations, db_session)
    statuses = _organization_statuses(integrations, db_session)
    shapes = _shapes(integrations, _external_apps(integrations, db_session))
    action_counts = count_integration_actions(
        [integration.id for integration in integrations], db_session
    )
    views: list[AdminIntegration] = []
    for integration in integrations:
        org_status = statuses[integration.id]
        needs_setup = org_status.state is ConnectionState.NOT_SET_UP
        shape, preset_id = shapes[integration.id]
        plugins = plugin_rows[integration.id]
        views.append(
            AdminIntegration(
                id=integration.id,
                kind=integration.kind,
                shape=shape,
                name=integration.name,
                description=integration.description,
                preset_id=preset_id,
                enabled=integration.enabled,
                auth_mode=integration.auth_mode,
                auth_method=integration.auth_method,
                plugins=[_plugin_ref(row) for row in plugins],
                created_by_email=(
                    creator_emails.get(integration.created_by_user_id)
                    if integration.created_by_user_id is not None
                    else None
                ),
                action_count=action_counts[integration.id],
                needs_setup=needs_setup,
                setup_reason=org_status.reason if needs_setup else None,
                organization_status=(
                    org_status
                    if integration.auth_mode is IntegrationAuthMode.SHARED
                    else None
                ),
                can_manage=manages_integration(user, plugins),
            )
        )
    return views


def list_admin_integrations(user: User, db_session: Session) -> list[AdminIntegration]:
    """Each integration for an organization-wide manager. Another manager
    gets the ones it manages and the ones it can see through a plugin."""
    integrations = list_integrations(db_session)
    plugin_rows = list_integration_plugin_rows(
        [integration.id for integration in integrations], db_session
    )
    visible: set[int] | None = None
    if not has_global_permission(user, Permission.MANAGE_ACTIONS):
        visible = set(
            list_integration_ids_held_by_plugins(
                visible_plugin_ids(user.id), db_session
            )
        )
    return _admin_views(
        user,
        [
            integration
            for integration in integrations
            if visible is None
            or integration.id in visible
            or manages_integration(user, plugin_rows[integration.id])
        ],
        plugin_rows,
        db_session,
    )


def _config_view(
    integration: Integration, shape: IntegrationShape, db_session: Session
) -> IntegrationConfigView:
    if shape is IntegrationShape.MCP_SERVER:
        server = get_mcp_server_for_integration(integration.id, db_session)
        if server is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The MCP server is missing.")
        return McpServerConfigInput(
            server_url=server.server_url,
            transport=server.transport or MCPTransport.STREAMABLE_HTTP,
        )
    if shape is IntegrationShape.OPENAPI:
        tool = get_openapi_tool_for_integration(integration.id, db_session)
        if tool is None or tool.openapi_schema is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The OpenAPI schema is missing.")
        return OpenApiConfigInput(openapi_spec=tool.openapi_schema)
    app = get_external_app_for_integration(integration.id, db_session)
    if app is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The app settings are missing.")
    if shape is IntegrationShape.PRESET:
        return PresetConfigView(preset_id=app.app_type.value)
    return CustomConfigInput(upstream_url_patterns=list(app.upstream_url_patterns))


def _oauth_client_view(
    oauth_client: IntegrationOAuthClient | None,
) -> OAuthClientView | None:
    if oauth_client is None:
        return None
    credentials = read_oauth_client(oauth_client)
    return OAuthClientView(
        provider_mode=oauth_client.provider_mode,
        authorization_url=oauth_client.authorization_url or "",
        token_url=oauth_client.token_url or "",
        scopes=oauth_client.scopes,
        additional_params=oauth_client.additional_params,
        pkce=oauth_client.pkce,
        client_id=credentials.client_id,
        has_client_secret=bool(credentials.client_secret),
    )


def keep_masked_values(
    values: Mapping[str, str], stored: Mapping[str, str]
) -> dict[str, str]:
    """A masked value means "keep the stored one", as a client sends back
    what it read."""
    resolved: dict[str, str] = {}
    for key, value in values.items():
        if not is_masked_credential(value):
            resolved[key] = value
            continue
        kept = stored.get(key)
        if kept is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"'{key}' was sent as a masked value but has no stored value to "
                "keep. Send the actual value.",
            )
        resolved[key] = kept
    return resolved


def masked_header_template(
    header_template: Mapping[str, str] | None,
) -> dict[str, str] | None:
    """A value with no placeholder is a stored secret, so it is masked."""
    if header_template is None:
        return None
    return {
        name: value if has_placeholder(value) else mask_string(value)
        for name, value in header_template.items()
    }


def admin_detail(
    user: User, integration: Integration, db_session: Session
) -> AdminIntegrationDetail:
    view = _admin_views(
        user,
        [integration],
        list_integration_plugin_rows([integration.id], db_session),
        db_session,
    )[0]
    managed = view.preset_id is not None and _is_onyx_managed(
        _preset_or_400(view.preset_id)
    )
    return AdminIntegrationDetail(
        **view.model_dump(),
        config=_config_view(integration, view.shape, db_session),
        credential_fields=_credential_fields(integration),
        header_template=(
            None
            if managed or not view.can_manage
            else masked_header_template(integration.header_template)
        ),
        users_can_save_always_allow=integration.users_can_save_always_allow,
        oauth_client=(
            None
            if managed
            else _oauth_client_view(get_oauth_client(db_session, integration.id))
        ),
        can_delete=view.can_manage and not managed,
    )


def admin_actions(
    integration: Integration, db_session: Session
) -> IntegrationActionsResponse:
    rows = get_policy_rows(db_session, integration.id, None)
    default_row = rows.admin.get(DEFAULT_ACTION_KEY)
    return IntegrationActionsResponse(
        default_policy=(
            STORED_TO_EFFECTIVE[default_row] if default_row is not None else None
        ),
        actions=_action_views(
            integration,
            list_integration_actions(integration.id, db_session),
            rows.admin,
        ),
    )


def _stored_value(
    policy: EffectivePolicy | None,
) -> IntegrationActionPolicyValue | None:
    return IntegrationActionPolicyValue(policy.value) if policy is not None else None


def _check_action_keys(
    integration: Integration, keys: Collection[str], db_session: Session
) -> None:
    known = {
        action.key for action in list_integration_actions(integration.id, db_session)
    }
    unknown = sorted(set(keys) - known)
    if unknown:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Unknown actions: " + ", ".join(unknown)
        )


def set_admin_actions__no_commit(
    integration: Integration, request: IntegrationActionsUpdate, db_session: Session
) -> None:
    _check_action_keys(integration, request.actions, db_session)
    values: dict[str, IntegrationActionPolicyValue | None] = {
        DEFAULT_ACTION_KEY: _stored_value(request.default_policy)
    }
    values.update(
        {key: _stored_value(policy) for key, policy in request.actions.items()}
    )
    set_policy_rows__no_commit(
        integration_id=integration.id,
        user_id=None,
        values=values,
        db_session=db_session,
    )


def refresh_actions__no_commit(
    user: User, integration: Integration, db_session: Session
) -> None:
    with _reaching(integration.name):
        _discover_and_sync(integration, user, db_session)


def _plugin_states(user: User, db_session: Session) -> dict[UUID, UserPluginState]:
    """Each plugin the user can see, with the user's install setting and
    choice."""
    return {
        state.plugin_id: state
        for state in load_user_plugin_states([user.id], db_session)
    }


def _visible_plugin_refs(
    states: Mapping[UUID, UserPluginState],
    integration_ids: Collection[int],
    db_session: Session,
) -> dict[int, list[MemberPluginRef]]:
    return {
        integration_id: [
            MemberPluginRef(
                **_plugin_ref(row).model_dump(exclude={"installation_policy"}),
                installation_policy=states[row.plugin_id].installation_policy,
                enabled=states[row.plugin_id].enabled,
            )
            for row in rows
            if row.plugin_id in states
        ]
        for integration_id, rows in list_integration_plugin_rows(
            integration_ids, db_session
        ).items()
    }


def _saved_credential_values(
    user: User, integrations: Collection[Integration], db_session: Session
) -> dict[int, dict[str, str]]:
    """The masked values the user saved for each api_key integration with a
    connection for each user."""
    keyed = {
        integration.id: credential_field_keys(integration)
        for integration in integrations
        if integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
        and integration.auth_method is IntegrationAuthMethod.API_KEY
    }
    connections = list_connections(db_session, list(keyed), user.id)
    values: dict[int, dict[str, str]] = {}
    for integration_id, keys in keyed.items():
        connection = connections.get((integration_id, user.id))
        if connection is None:
            continue
        fields = read_connection_secret(connection).fields
        values[integration_id] = {
            key: mask_string(fields[key]) for key in keys if key in fields
        }
    return values


def _member_views(
    user: User,
    integrations: Collection[Integration],
    plugin_refs: Mapping[int, list[MemberPluginRef]],
    db_session: Session,
) -> list[MemberIntegration]:
    statuses = integration_statuses(integrations, user, db_session)
    external_apps = _external_apps(integrations, db_session)
    shapes = _shapes(integrations, external_apps)
    mcp_servers = list_mcp_servers_by_integration(
        [
            integration.id
            for integration in integrations
            if integration.mcp_server_id is not None
        ],
        db_session,
    )
    saved_values = _saved_credential_values(user, integrations, db_session)
    views: list[MemberIntegration] = []
    for integration in integrations:
        shape, preset_id = shapes[integration.id]
        app = external_apps.get(integration.id)
        server = mcp_servers.get(integration.id)
        views.append(
            MemberIntegration(
                id=integration.id,
                kind=integration.kind,
                shape=shape,
                name=integration.name,
                description=integration.description,
                preset_id=preset_id,
                auth_mode=integration.auth_mode,
                auth_method=integration.auth_method,
                credential_fields=_credential_fields(integration),
                status=statuses[integration.id],
                plugins=plugin_refs[integration.id],
                users_can_save_always_allow=integration.users_can_save_always_allow,
                credential_values=saved_values.get(integration.id, {}),
                external_app_id=app.id if app is not None else None,
                service_urls=craft_service_urls(app) if app is not None else [],
                mcp_server_id=server.id if server is not None else None,
                server_url=server.server_url if server is not None else None,
            )
        )
    return views


def list_member_integrations(
    user: User, db_session: Session
) -> list[MemberIntegration]:
    states = _plugin_states(user, db_session)
    integration_ids = list_integration_ids_held_by_plugins(list(states), db_session)
    return _member_views(
        user,
        [
            integration
            for integration in list_integrations_by_ids(integration_ids, db_session)
            if integration.enabled
        ],
        _visible_plugin_refs(states, integration_ids, db_session),
        db_session,
    )


def get_member_integration(
    user: User, integration_id: int, db_session: Session
) -> Integration:
    integration = _integration_or_404(integration_id, db_session)
    if not user_can_see_integration(db_session, integration_id, user.id):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")
    return integration


def member_actions(
    user: User, integration: Integration, db_session: Session
) -> list[MemberAction]:
    rows = get_policy_rows(db_session, integration.id, user.id)
    return [
        MemberAction(
            **view.model_dump(),
            user_policy=(
                "allow"
                if rows.user.get(view.key) is IntegrationActionPolicyValue.ALLOW
                else None
            ),
        )
        for view in _action_views(
            integration,
            list_integration_actions(integration.id, db_session),
            rows.admin,
        )
    ]


def member_detail(
    user: User, integration: Integration, db_session: Session
) -> MemberIntegrationDetail:
    plugin_refs = _visible_plugin_refs(
        _plugin_states(user, db_session), [integration.id], db_session
    )
    return MemberIntegrationDetail(
        **_member_views(user, [integration], plugin_refs, db_session)[0].model_dump(),
        actions=member_actions(user, integration, db_session),
    )


def action_grants(
    user: User, integration: Integration, db_session: Session
) -> ActionGrantsResponse:
    return ActionGrantsResponse(
        users_can_save_always_allow=integration.users_can_save_always_allow,
        actions=member_actions(user, integration, db_session),
    )


def set_action_grants__no_commit(
    user: User,
    integration: Integration,
    grants: Mapping[str, str | None],
    db_session: Session,
) -> None:
    if not integration.users_can_save_always_allow:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            f"Your admin does not let users save Always allow for {integration.name}.",
        )
    _check_action_keys(integration, grants, db_session)
    admin_policies = {
        view.key: view.effective_admin_policy
        for view in action_views(integration, db_session)
    }
    for key, value in sorted(grants.items()):
        if value != "allow":
            continue
        if admin_policies[key] is EffectivePolicy.BLOCKED:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Your admin blocks {key}. You cannot save Always allow for it.",
            )
        if always_asks(integration.kind, key):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Craft asks for approval for each {key} request. "
                "You cannot save Always allow for it.",
            )
        if admin_policies[key] is EffectivePolicy.ALLOW:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Your admin already allows {key}. Always allow is not necessary.",
            )
    set_policy_rows__no_commit(
        integration_id=integration.id,
        user_id=user.id,
        values={
            key: IntegrationActionPolicyValue.ALLOW if value == "allow" else None
            for key, value in grants.items()
        },
        db_session=db_session,
    )


def agent_catalog(user: User, db_session: Session) -> list[AgentPluginOption]:
    visible = get_visible_plugin_ids(user.id, db_session)
    integrations = [
        integration
        for integration in list_integrations_by_ids(
            list_integration_ids_held_by_plugins(visible, db_session), db_session
        )
        if integration.enabled
    ]
    integration_ids = [integration.id for integration in integrations]
    shapes = _shapes(integrations, _external_apps(integrations, db_session))
    actions = list_action_summaries(integration_ids, db_session)
    admin_rows = list_admin_policy_rows(db_session, integration_ids)
    integration_options = {
        integration.id: AgentIntegrationOption(
            id=integration.id,
            name=integration.name,
            kind=integration.kind,
            shape=shapes[integration.id][0],
            users_can_save_always_allow=integration.users_can_save_always_allow,
            actions=_action_views(
                integration, actions[integration.id], admin_rows[integration.id]
            ),
        )
        for integration in integrations
    }
    options: dict[UUID, AgentPluginOption] = {}
    for integration_id, rows in list_integration_plugin_rows(
        list(integration_options), db_session
    ).items():
        for row in rows:
            if row.plugin_id not in visible:
                continue
            option = options.setdefault(
                row.plugin_id,
                AgentPluginOption(
                    plugin_id=row.plugin_id,
                    plugin_name=row.plugin_name,
                    description=row.plugin_description,
                    integrations=[],
                ),
            )
            option.integrations.append(integration_options[integration_id])
    return sorted(options.values(), key=lambda option: option.plugin_name.lower())


def craft_users_of_integration(integration_id: int, db_session: Session) -> set[UUID]:
    """The users with a running sandbox who can see a plugin that holds the
    integration. Read it before a delete."""
    return affected_user_ids_for_plugins(
        [
            row.plugin_id
            for row in list_integration_plugin_rows([integration_id], db_session)[
                integration_id
            ]
        ],
        db_session,
    )


def reload_craft_sessions(user_ids: set[UUID], db_session: Session) -> None:
    """Call after the commit; best-effort."""
    if not user_ids:
        return
    # Imported here: the build layer and the skill push import this package.
    from onyx.server.features.build.session.sandbox_lifecycle import (
        refresh_mcp_config_hashes_for_users,
    )
    from onyx.skills.push import push_skills_and_commit

    refresh_mcp_config_hashes_for_users(user_ids, db_session)
    push_skills_and_commit(user_ids, db_session)
