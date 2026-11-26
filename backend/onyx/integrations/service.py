"""The logic of the integration API: who manages an integration, create,
update and delete, the views, the action policies and the connections."""

import json
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import requests
from graphql import get_introspection_query
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
    PluginInstallationPolicy,
)
from onyx.db.external_app import associate_built_in_skill__no_commit
from onyx.db.integration import (
    create_external_app_row__no_commit,
    create_graphql_app_row__no_commit,
    create_mcp_server_row__no_commit,
    create_openapi_tool_row__no_commit,
    delete_integration__no_commit,
    delete_oauth_client__no_commit,
    get_api_app_for_integration,
    get_external_app_for_integration,
    get_integration_by_id,
    get_mcp_server_for_integration,
    insert_integration__no_commit,
    list_external_apps_by_integration,
    list_integration_actions,
    list_integrations,
    list_integrations_by_ids,
    list_mcp_servers_by_integration,
    lock_integration,
    lock_integration__no_commit,
    rename_kind_row__no_commit,
    replace_integration_actions__no_commit,
    set_policy_rows__no_commit,
    upsert_oauth_client__no_commit,
    write_openapi_document__no_commit,
)
from onyx.db.integration_access import (
    UserIntegrationState,
    affected_user_ids_for_integrations,
    group_limited_integration_ids,
    load_integration_group_settings,
    load_integration_shares,
    load_user_integration_states,
    set_integration_preferences__no_commit,
    user_can_use_integration,
)
from onyx.db.integration_connection import (
    get_oauth_client,
    get_oauth_clients,
    list_connections,
)
from onyx.db.integration_policy import get_policy_rows, list_admin_policy_rows
from onyx.db.models import (
    ExternalApp,
    Integration,
    IntegrationAction,
    IntegrationOAuthClient,
    User,
)
from onyx.db.users import fetch_users_by_ids
from onyx.db.utils import UNSET
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import get_onyx_managed_provider
from onyx.integrations.actions import (
    count_actions,
    integration_actions,
    integration_actions_by_id,
)
from onyx.integrations.connection_models import (
    SIGN_IN_SETTINGS_CHANGED_REASON,
    ConnectionState,
    read_connection_secret,
    read_oauth_client,
)
from onyx.integrations.connections import (
    IntegrationStatus,
    MissingHeaderValueError,
    connect_with_fields__no_commit,
    credential_field_keys,
    credential_fields_json,
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
from onyx.integrations.craft import craft_service_urls
from onyx.integrations.kinds.api import (
    sync_integration_actions__no_commit,
)
from onyx.integrations.kinds.mcp_server import (
    check_mcp_credential_fields,
    fetch_mcp_actions,
    mcp_action_specs,
)
from onyx.integrations.models import (
    EffectivePolicy,
    IntegrationActionSpec,
)
from onyx.integrations.openapi_endpoints import (
    EndpointLinesError,
    apply_endpoint_lines,
    drop_uncallable_operations,
    endpoint_lines,
)
from onyx.integrations.policy import (
    DEFAULT_ACTION_KEY,
    STORED_TO_EFFECTIVE,
    action_default_policy,
    admin_policy,
    always_asks,
)
from onyx.integrations.presets import (
    PRESET_OAUTH_REDIRECT_URI,
    PRESETS,
    Preset,
    get_preset,
)
from onyx.server.features.integrations.models import (
    ActionGrantsResponse,
    AdminIntegration,
    AdminIntegrationDetail,
    AgentIntegrationOption,
    CredentialField,
    CustomConfigView,
    GraphQLConfigInput,
    GraphQLIntrospectRequest,
    IntegrationAccess,
    IntegrationActionsResponse,
    IntegrationActionsUpdate,
    IntegrationActionView,
    IntegrationConfigInput,
    IntegrationConfigView,
    IntegrationCreate,
    IntegrationGroupSettingView,
    IntegrationGroupShare,
    IntegrationShape,
    IntegrationUpdate,
    McpServerConfigInput,
    MemberAction,
    MemberIntegration,
    MemberIntegrationDetail,
    MemberIntegrationState,
    OAuthClientInput,
    OAuthClientView,
    OpenApiConfigInput,
    OpenApiConfigView,
    OpenApiEndpointsRequest,
    PresetConfigInput,
    PresetConfigView,
    PresetView,
)
from onyx.server.features.mcp.client import discover_mcp_tools
from onyx.server.features.mcp.ssrf import validate_mcp_url
from onyx.server.security.models import outbound_ssrf_params, ssrf_error_hint
from onyx.server.security.store import get_security_settings
from onyx.tools.tool_implementations.custom.custom_tool import validate_custom_tool_url
from onyx.tools.tool_implementations.custom.graphql_tool import introspection_to_sdl
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_url,
    parse_openapi_document,
    validate_openapi_schema,
)
from onyx.tools.tool_implementations.http_request import (
    ToolRequestError,
    ToolRequestFailure,
    send_tool_request,
)
from onyx.utils.encryption import is_masked_credential, mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, ssrf_safe_get
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

_MAX_SPEC_BYTES = 5 * 1024 * 1024
_SPEC_FETCH_TIMEOUT_SECONDS = 15

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


def is_private(integration: Integration) -> bool:
    """Private: only the owner and the shares have access."""
    return integration.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE


def manages_integration(user: User, integration: Integration) -> bool:
    """An organization-wide action manager manages each integration. A scoped
    manager manages the integrations that it owns, while they are private."""
    authority = has_permission(user, Permission.MANAGE_ACTIONS)
    if authority is PermissionAuthority.GLOBAL:
        return True
    return (
        authority is not PermissionAuthority.NONE
        and integration.owner_user_id == user.id
        and is_private(integration)
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
    if not (
        manages_integration(user, integration)
        or user_can_use_integration(db_session, integration.id, user.id)
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Integration not found.")
    return integration


def get_manageable_integration(
    user: User, integration_id: int, db_session: Session, *, lock: bool = False
) -> Integration:
    integration = _integration_or_404(integration_id, db_session, lock=lock)
    if manages_integration(user, integration):
        return integration
    if user_can_use_integration(db_session, integration.id, user.id):
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
    integrations: Collection[Integration],
    external_apps: Mapping[int, ExternalApp],
    *,
    skip_unknown: bool = False,
) -> dict[int, tuple[IntegrationShape, str | None]]:
    """The shape and the preset id of each integration. ``skip_unknown``
    leaves out an integration with no shape, e.g. one that a later release
    wrote, so that a list still shows the others."""
    shapes: dict[int, tuple[IntegrationShape, str | None]] = {}
    for integration in integrations:
        if integration.kind is IntegrationKind.MCP:
            shapes[integration.id] = (IntegrationShape.MCP_SERVER, None)
            continue
        if integration.tool_id is not None:
            shapes[integration.id] = (IntegrationShape.OPENAPI, None)
            continue
        # For one release a REST app also has its tool row, so an api_app
        # row alone is a GraphQL app.
        if integration.api_app_id is not None:
            shapes[integration.id] = (IntegrationShape.GRAPHQL, None)
            continue
        app = external_apps.get(integration.id)
        if app is None:
            if skip_unknown:
                logger.warning(
                    "Skipping integration %s: it has no settings of a known shape.",
                    integration.id,
                )
                continue
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


def _preset_view(preset: Preset) -> PresetView:
    descriptor = preset.provider.spec.descriptor
    oauth = (
        preset.provider
        if isinstance(preset.provider, OAuthExternalAppProvider)
        else None
    )
    return PresetView(
        id=preset.id,
        name=preset.name,
        auth_methods=_preset_methods(preset),
        required_org_credential_fields=[
            CredentialField(key=field.key, label=field.label, secret=field.secret)
            for field in descriptor.required_org_credential_fields
        ],
        setup_steps=list(descriptor.setup_steps),
        setup_url=descriptor.setup_url,
        callback_url=PRESET_OAUTH_REDIRECT_URI if oauth else None,
        scopes=oauth.spec.oauth.requested_scopes() if oauth else [],
    )


def preset_views() -> list[PresetView]:
    """The presets an admin can add."""
    return [
        _preset_view(preset)
        for preset in sorted(PRESETS.values(), key=lambda preset: preset.name)
        if not _is_onyx_managed(preset)
    ]


def _allowed_methods(
    shape: IntegrationShape, preset: Preset | None
) -> list[IntegrationAuthMethod | None]:
    if shape is IntegrationShape.PRESET and preset is not None:
        return _preset_methods(preset)
    return list(_TOKEN_METHODS)


def _check_no_query_or_fragment(server_url: str) -> None:
    try:
        parsed = urlparse(server_url)
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Server URL '{server_url}' is not valid: {e}",
        ) from e
    if parsed.query or parsed.fragment:
        # Tools append the endpoint path to the whole server URL.
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Server URL '{server_url}' cannot have a query or a fragment.",
        )


def validate_openapi_definition(definition: dict[str, Any]) -> None:
    try:
        validate_openapi_schema(definition)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e
    server_url = openapi_to_url(definition)
    try:
        _check_no_query_or_fragment(server_url)
        # No DNS at save time; each call resolves and checks again.
        validate_custom_tool_url(server_url, resolve_dns=False)
    except (SSRFException, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Server URL '{server_url}' is not allowed: {e}",
        ) from e


def _openapi_document(
    config: OpenApiConfigInput,
    stored: str | None,
    *,
    title: str,
    description: str | None,
) -> tuple[str, dict[str, Any]]:
    """The document to store and its parsed spec: the one sent, or the
    endpoint lines applied to the one sent, else to ``stored``. A line error
    names its line in ``extra.line_errors``."""
    try:
        if config.endpoints is None:
            if config.openapi_document is None:
                raise RuntimeError("Bug: the model requires a document or lines.")
            document = config.openapi_document
        else:
            document = apply_endpoint_lines(
                (
                    config.openapi_document
                    if config.openapi_document is not None
                    else stored
                ),
                title=title,
                description=description,
                base_url=(config.base_url or "").strip(),
                lines=config.endpoints,
            )
        spec = parse_openapi_document(document)
    except EndpointLinesError as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            str(e),
            extra={"line_errors": [error.model_dump() for error in e.errors]},
        ) from e
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e
    validate_openapi_definition(spec)
    return document, spec


def _openapi_view(document: str, spec: dict[str, Any]) -> OpenApiConfigView:
    try:
        base_url = openapi_to_url(spec)
    except ValueError:
        base_url = ""
    return OpenApiConfigView(
        openapi_document=document, base_url=base_url, endpoints=endpoint_lines(spec)
    )


def _imported_view(document: str) -> OpenApiConfigView:
    """The view of a spec to import, without the operations that no tool can
    call. Runs the checks of create except the server URL ones: the client
    may still set the URL. A document that is not a spec at all is
    ``INVALID_INPUT``; a spec that fails the checks is ``VALIDATION_ERROR``."""
    try:
        spec = parse_openapi_document(document)
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"This is not an OpenAPI spec: {e}"
        ) from e
    if "openapi" not in spec and "swagger" not in spec:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This is not an OpenAPI spec: it has no `openapi` field.",
        )
    try:
        document, skipped = drop_uncallable_operations(document, spec)
        validate_openapi_schema(spec, check_server_url=False)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e
    view = _openapi_view(document, spec)
    view.skipped = skipped
    return view


def import_openapi_document(request: OpenApiEndpointsRequest) -> OpenApiConfigView:
    """The base URL and the endpoint lines of a spec to import. A spec URL
    that Onyx cannot fetch is ``BAD_GATEWAY``."""
    if request.openapi_document is not None:
        if len(request.openapi_document.encode()) > _MAX_SPEC_BYTES:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE, "The spec is larger than 5 MB."
            )
        return _imported_view(request.openapi_document)
    if request.spec_url is None:
        raise RuntimeError("Bug: the model requires the spec text or a URL.")
    spec_url = request.spec_url.strip()
    policy = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    body = bytearray()
    try:
        with ssrf_safe_get(
            spec_url,
            timeout=_SPEC_FETCH_TIMEOUT_SECONDS,
            trust_env=False,
            allow_private_network=policy.allow_private_network,
            block_loopback_and_link_local=policy.block_loopback_and_link_local,
            block_link_local_only=policy.block_link_local_only,
            stream=True,
        ) as response:
            if not 200 <= response.status_code < 300:
                raise OnyxError(
                    OnyxErrorCode.BAD_GATEWAY,
                    f"The spec URL answered with HTTP {response.status_code}.",
                )
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_SPEC_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        "The spec is larger than 5 MB.",
                    )
    except (SSRFException, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"Onyx cannot fetch the spec: {e}{ssrf_error_hint(spec_url, e)}",
        ) from e
    except requests.RequestException as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY, f"Onyx could not fetch the spec: {e}"
        ) from e
    view = _imported_view(body.decode("utf-8", errors="replace"))
    # The client hides the base URL field for the single server URL of a
    # fetched spec, so the admin cannot correct it after the import.
    _check_no_query_or_fragment(view.base_url)
    return view


def _graphql_endpoint_url(config: GraphQLConfigInput) -> str:
    """The stripped endpoint URL. Raises ``OnyxError`` for a blocked host."""
    endpoint_url = config.endpoint_url.strip()
    try:
        # No DNS at save time; each call resolves and checks again.
        validate_custom_tool_url(endpoint_url, resolve_dns=False)
    except (SSRFException, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Endpoint URL '{endpoint_url}' is not allowed: {e}",
        ) from e
    return endpoint_url


def introspect_graphql_endpoint(
    request: GraphQLIntrospectRequest,
) -> GraphQLConfigInput:
    """The schema of an endpoint that answers an introspection query with no
    sign-in. An endpoint that Onyx cannot reach is ``BAD_GATEWAY``."""
    endpoint_url = request.endpoint_url.strip()
    try:
        response = send_tool_request(
            "POST",
            endpoint_url,
            headers={},
            # An admin setup fetch: the admin SSRF level, as for the spec URL
            # import and MCP servers, not the chat tool policy.
            ssrf=outbound_ssrf_params(get_security_settings().ssrf_protection_level),
            max_response_bytes=_MAX_SPEC_BYTES,
            json_body={"query": get_introspection_query(descriptions=True)},
        )
    except ToolRequestError as e:
        reason: str = e.failure.value
        if e.failure is ToolRequestFailure.BLOCKED and isinstance(
            e.__cause__, Exception
        ):
            reason = f"{e.__cause__}{ssrf_error_hint(endpoint_url, e.__cause__)}"
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY, f"Onyx could not reach the endpoint: {reason}"
        ) from e
    if not response.ok:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"The endpoint answered with HTTP {response.status_code}.",
        )
    if response.truncated:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            "The schema is larger than 5 MB. Upload a smaller SDL file.",
        )
    try:
        sdl = introspection_to_sdl(json.loads(response.body))
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    return GraphQLConfigInput(endpoint_url=endpoint_url, graphql_schema=sdl)


_TOKEN_PLACEHOLDERS = frozenset({"access_token", "refresh_token", "token_type"})


def _check_template_fits(
    auth_method: IntegrationAuthMethod | None,
    header_template: Mapping[str, str] | None,
) -> None:
    """A header template may use only the placeholders the sign-in method
    fills; an API key method fills the fields that the template names."""
    if auth_method is IntegrationAuthMethod.API_KEY or not header_template:
        return
    allowed = _TOKEN_PLACEHOLDERS if auth_method is not None else frozenset()
    unknown = sorted(set(header_field_keys(header_template)) - allowed)
    if unknown:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This sign-in method cannot fill the header placeholders: "
            + ", ".join(unknown),
        )


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
    """Make the integration, its kind row, its OAuth client and its actions. The user is its owner. For the organization,
    it is Available to each user; else it is private and on for its owner.
    The caller commits; an error leaves nothing.
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
    _check_template_fits(auth_method, header_template)
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
    openapi = (
        _openapi_document(config, None, title=name, description=request.description)
        if isinstance(config, OpenApiConfigInput)
        else None
    )
    graphql_endpoint_url = (
        _graphql_endpoint_url(config)
        if isinstance(config, GraphQLConfigInput)
        else None
    )
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
    api_app_id: int | None = None
    if isinstance(config, McpServerConfigInput):
        mcp_server_id = create_mcp_server_row__no_commit(
            name=name,
            description=request.description,
            owner_email=user.email,
            server_url=config.server_url,
            transport=config.transport,
            db_session=db_session,
        ).id
    elif openapi is not None:
        tool_id = create_openapi_tool_row__no_commit(
            name=name,
            description=request.description,
            user_id=user.id,
            openapi_spec=openapi[1],
            db_session=db_session,
        ).id
    elif isinstance(config, GraphQLConfigInput) and graphql_endpoint_url is not None:
        api_app_id = create_graphql_app_row__no_commit(
            endpoint_url=graphql_endpoint_url,
            graphql_schema=config.graphql_schema,
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
    integration = insert_integration__no_commit(
        name=name,
        description=request.description,
        owner_user_id=user.id,
        installation_policy=(
            PluginInstallationPolicy.AVAILABLE
            if request.for_organization
            else PluginInstallationPolicy.NOT_AVAILABLE
        ),
        auth_mode=request.auth_mode,
        auth_method=auth_method,
        credential_fields=(
            credential_fields_json(request.credential_fields, header_template)
            if auth_method is IntegrationAuthMethod.API_KEY
            else None
        ),
        header_template=header_template,
        mcp_server_id=mcp_server_id,
        external_app_id=external_app_id,
        tool_id=tool_id,
        api_app_id=api_app_id,
        db_session=db_session,
    )
    if openapi is not None:
        write_openapi_document__no_commit(integration, *openapi, db_session)

    if auth_method is IntegrationAuthMethod.OAUTH2 and request.oauth_client:
        _write_oauth_client(
            integration,
            request.oauth_client,
            shape,
            org_credentials,
            keep_secret=False,
            db_session=db_session,
        )

    if not request.for_organization:
        set_integration_preferences__no_commit(
            user.id, [integration.id], True, db_session
        )

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
        stored = get_api_app_for_integration(integration.id, db_session)
        document, spec = _openapi_document(
            config,
            stored.openapi_document if stored is not None else None,
            title=integration.name,
            description=integration.description,
        )
        write_openapi_document__no_commit(integration, document, spec, db_session)
        return True
    if isinstance(config, GraphQLConfigInput):
        endpoint_url = _graphql_endpoint_url(config)
        api_app = get_api_app_for_integration(integration.id, db_session)
        if api_app is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The GraphQL app is missing.")
        api_app.base_url = endpoint_url
        api_app.graphql_schema = config.graphql_schema
        return True
    app = get_external_app_for_integration(integration.id, db_session)
    if app is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The app settings are missing.")
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
                or OAuthClientInput(provider_mode=IntegrationOAuthProviderMode.PRESET),
                shape,
                org_credentials,
                keep_secret=True,
                db_session=db_session,
            )
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


_SIGN_IN_FIELDS = frozenset(
    {"auth_mode", "auth_method", "header_template", "credential_fields", "oauth_client"}
)


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
    if "header_template" in fields:
        _check_template_fits(auth_method, header_template)
    if auth_method is not integration.auth_method or fields & {
        "config",
        "header_template",
    }:
        _check_onyx_login(user, auth_method)
    # A save that changes no sign-in setting keeps the stored one. A migrated
    # API key integration has no header template: its headers are in its
    # legacy connection.
    if fields & _SIGN_IN_FIELDS:
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
        integration.credential_fields = credential_fields_json(
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


def member_state(
    state: UserIntegrationState | None,
    integration: Integration,
    status: IntegrationStatus,
) -> MemberIntegrationState:
    """The one rule for what a user gets from an integration. ``state`` is
    None when the user has no access. ``status`` is the connection status
    for the user."""
    if state is None:
        return MemberIntegrationState.NO_ACCESS
    if not integration.enabled:
        return MemberIntegrationState.TURNED_OFF
    if not state.turned_on:
        return MemberIntegrationState.TURN_ON
    if status.state is not ConnectionState.CONNECTED:
        return MemberIntegrationState.SIGN_IN
    return MemberIntegrationState.ON


def _access_views(
    user: User,
    integrations: Collection[Integration],
    states: Mapping[int, UserIntegrationState],
    statuses: Mapping[int, IntegrationStatus],
    db_session: Session,
) -> dict[int, IntegrationAccess]:
    """The access facts of each integration for the user. ``statuses`` are
    the connection statuses for the user."""
    owner_emails = _owner_emails(integrations, db_session)
    views: dict[int, IntegrationAccess] = {}
    for integration in integrations:
        state = states.get(integration.id)
        views[integration.id] = IntegrationAccess(
            state=member_state(state, integration, statuses[integration.id]),
            installation_policy=(
                state.installation_policy
                if state is not None
                else integration.installation_policy
            ),
            user_choice=state.choice if state is not None else None,
            user_enabled=state.turned_on if state is not None else False,
            # The owner of an integration for the organization stays hidden.
            owner_email=(
                owner_emails.get(integration.id) if is_private(integration) else None
            ),
            is_owner=integration.owner_user_id == user.id,
            can_manage=manages_integration(user, integration),
            shared_with_everyone=not is_private(integration),
        )
    return views


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
            always_asks=always_asks(action.key),
        )
        for action in actions
    ]


def action_views(
    integration: Integration, db_session: Session
) -> list[IntegrationActionView]:
    rows = get_policy_rows(db_session, integration.id, None)
    return _action_views(integration_actions(integration.id, db_session), rows.admin)


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


def _owner_emails(
    integrations: Collection[Integration], db_session: Session
) -> dict[int, str]:
    """The email of the owner of each integration that has one."""
    owner_ids = {
        integration.id: integration.owner_user_id
        for integration in integrations
        if integration.owner_user_id is not None
    }
    emails = {
        owner.id: owner.email
        for owner in fetch_users_by_ids(db_session, list(set(owner_ids.values())))
    }
    return {
        integration_id: emails[owner_id]
        for integration_id, owner_id in owner_ids.items()
        if owner_id in emails
    }


def _admin_views(
    user: User,
    integrations: Collection[Integration],
    db_session: Session,
    *,
    skip_unknown: bool = False,
) -> list[AdminIntegration]:
    shapes = _shapes(
        integrations,
        _external_apps(integrations, db_session),
        skip_unknown=skip_unknown,
    )
    integrations = [i for i in integrations if i.id in shapes]
    owner_emails = _owner_emails(integrations, db_session)
    statuses = _organization_statuses(integrations, db_session)
    access = _access_views(
        user,
        integrations,
        _integration_states(user, db_session),
        integration_statuses(integrations, user, db_session),
        db_session,
    )
    action_counts = count_actions(
        [integration.id for integration in integrations], db_session
    )
    views: list[AdminIntegration] = []
    for integration in integrations:
        org_status = statuses[integration.id]
        needs_setup = org_status.state is ConnectionState.NOT_SET_UP
        shape, preset_id = shapes[integration.id]
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
                installation_policy=integration.installation_policy,
                access=access[integration.id],
                created_by_email=owner_emails.get(integration.id),
                action_count=action_counts[integration.id],
                needs_setup=needs_setup,
                setup_reason=org_status.reason if needs_setup else None,
                organization_status=(
                    org_status
                    if integration.auth_mode is IntegrationAuthMode.SHARED
                    else None
                ),
                can_manage=manages_integration(user, integration),
            )
        )
    return views


def list_admin_integrations(user: User, db_session: Session) -> list[AdminIntegration]:
    """Each integration for an organization-wide manager. Another manager
    gets the ones it manages and the ones it has access to."""
    integrations = list_integrations(db_session)
    if not has_global_permission(user, Permission.MANAGE_ACTIONS):
        accessible = set(_integration_states(user, db_session))
        integrations = [
            integration
            for integration in integrations
            if integration.id in accessible or manages_integration(user, integration)
        ]
    return _admin_views(user, integrations, db_session, skip_unknown=True)


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
        api_app = get_api_app_for_integration(integration.id, db_session)
        if api_app is None or api_app.openapi_document is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The OpenAPI schema is missing.")
        try:
            spec = parse_openapi_document(api_app.openapi_document)
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e
        return _openapi_view(api_app.openapi_document, spec)
    if shape is IntegrationShape.GRAPHQL:
        api_app = get_api_app_for_integration(integration.id, db_session)
        if api_app is None or api_app.graphql_schema is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "The GraphQL schema is missing.")
        return GraphQLConfigInput(
            endpoint_url=api_app.base_url, graphql_schema=api_app.graphql_schema
        )
    app = get_external_app_for_integration(integration.id, db_session)
    if app is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "The app settings are missing.")
    if shape is IntegrationShape.PRESET:
        return PresetConfigView(preset_id=app.app_type.value)
    return CustomConfigView(upstream_url_patterns=list(app.upstream_url_patterns))


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
    view = _admin_views(user, [integration], db_session)[0]
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
        group_settings=[
            IntegrationGroupSettingView(**setting.model_dump())
            for setting in load_integration_group_settings(integration.id, db_session)
        ],
        group_shares=[
            IntegrationGroupShare(group_id=share.group_id, group_name=share.group_name)
            for share in load_integration_shares(
                integration.id, db_session
            ).group_shares
        ],
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
            integration_actions(integration.id, db_session),
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
    known = {action.key for action in integration_actions(integration.id, db_session)}
    unknown = sorted(set(keys) - known)
    if unknown:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Unknown actions: " + ", ".join(unknown)
        )


def save_connection_fields__no_commit(
    integration: Integration,
    user: User | None,
    fields: Mapping[str, str],
    db_session: Session,
) -> None:
    """Check the key with the server of an MCP integration, then save the
    connection of ``user``, or of the organization when ``user`` is None.
    The check runs before the save locks the integration row."""
    check_mcp_credential_fields(
        integration, fields, user.email if user is not None else None, db_session
    )
    connect_with_fields__no_commit(integration, user, fields, db_session)


def set_admin_actions__no_commit(
    integration: Integration, request: IntegrationActionsUpdate, db_session: Session
) -> None:
    _check_action_keys(integration, request.actions, db_session)
    if integration.kind is IntegrationKind.API and not list_integration_actions(
        integration.id, db_session
    ):
        # The migration writes no API actions, and a read never writes them.
        sync_integration_actions__no_commit(integration, db_session)
    # Only the fields that the request names change, so a save from a stale
    # page does not undo a newer save of another action.
    values: dict[str, IntegrationActionPolicyValue | None] = {}
    if "default_policy" in request.model_fields_set:
        values[DEFAULT_ACTION_KEY] = _stored_value(request.default_policy)
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


def _integration_states(
    user: User, db_session: Session
) -> dict[int, UserIntegrationState]:
    """Each integration the user has access to, with the user's install
    setting and choice."""
    return {
        state.integration_id: state
        for state in load_user_integration_states([user.id], db_session)
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
    states: Mapping[int, UserIntegrationState],
    db_session: Session,
    *,
    skip_unknown: bool = False,
) -> list[MemberIntegration]:
    external_apps = _external_apps(integrations, db_session)
    shapes = _shapes(integrations, external_apps, skip_unknown=skip_unknown)
    integrations = [i for i in integrations if i.id in shapes]
    statuses = integration_statuses(integrations, user, db_session)
    access = _access_views(user, integrations, states, statuses, db_session)
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
                access=access[integration.id],
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
    """Each integration the user has access to, also one that an admin
    turned off (``access.state`` is ``turned_off``), and each one an admin
    made available only to groups the user is not in (``no_access``)."""
    states = _integration_states(user, db_session)
    return _member_views(
        user,
        list_integrations_by_ids(list(states), db_session),
        states,
        db_session,
        skip_unknown=True,
    ) + _no_access_views(
        user,
        list_integrations_by_ids(
            group_limited_integration_ids(user.id, db_session), db_session
        ),
        db_session,
    )


def _no_access_views(
    user: User, integrations: Collection[Integration], db_session: Session
) -> list[MemberIntegration]:
    """Only what a row shows: no configuration, connection or owner."""
    shapes = _shapes(
        integrations, _external_apps(integrations, db_session), skip_unknown=True
    )
    integrations = [i for i in integrations if i.id in shapes]
    status = IntegrationStatus(state=ConnectionState.NOT_CONNECTED, reason=None)
    access = _access_views(
        user,
        integrations,
        {},
        {integration.id: status for integration in integrations},
        db_session,
    )
    return [
        MemberIntegration(
            id=integration.id,
            kind=integration.kind,
            shape=shapes[integration.id][0],
            name=integration.name,
            description=integration.description,
            preset_id=shapes[integration.id][1],
            auth_mode=integration.auth_mode,
            auth_method=integration.auth_method,
            credential_fields=[],
            status=status,
            access=access[integration.id].model_copy(update={"owner_email": None}),
            users_can_save_always_allow=integration.users_can_save_always_allow,
            credential_values={},
            external_app_id=None,
            service_urls=[],
            mcp_server_id=None,
            server_url=None,
        )
        for integration in integrations
    ]


def member_view(
    user: User, integration: Integration, db_session: Session
) -> MemberIntegration:
    states = {
        state.integration_id: state
        for state in load_user_integration_states(
            [user.id], db_session, [integration.id]
        )
    }
    return _member_views(user, [integration], states, db_session)[0]


def get_member_integration(
    user: User, integration_id: int, db_session: Session
) -> Integration:
    integration = _integration_or_404(integration_id, db_session)
    if not user_can_use_integration(db_session, integration_id, user.id):
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
            integration_actions(integration.id, db_session),
            rows.admin,
        )
    ]


def member_detail(
    user: User, integration: Integration, db_session: Session
) -> MemberIntegrationDetail:
    return MemberIntegrationDetail(
        **member_view(user, integration, db_session).model_dump(),
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
    lock_integration__no_commit(integration.id, db_session)
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
        if always_asks(key):
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


def agent_catalog(user: User, db_session: Session) -> list[AgentIntegrationOption]:
    """Each integration that the user has access to and that an admin did
    not turn off, in name order."""
    enabled = [
        integration
        for integration in list_integrations_by_ids(
            list(_integration_states(user, db_session)), db_session
        )
        if integration.enabled
    ]
    shapes = _shapes(enabled, _external_apps(enabled, db_session), skip_unknown=True)
    integrations = [i for i in enabled if i.id in shapes]
    integration_ids = [integration.id for integration in integrations]
    actions = integration_actions_by_id(integration_ids, db_session)
    admin_rows = list_admin_policy_rows(db_session, integration_ids)
    return [
        AgentIntegrationOption(
            id=integration.id,
            name=integration.name,
            description=integration.description,
            kind=integration.kind,
            shape=shapes[integration.id][0],
            users_can_save_always_allow=integration.users_can_save_always_allow,
            actions=_action_views(actions[integration.id], admin_rows[integration.id]),
        )
        for integration in sorted(
            integrations,
            key=lambda integration: (integration.name.lower(), integration.id),
        )
    ]


def craft_users_of_integration(integration_id: int, db_session: Session) -> set[UUID]:
    """The users with a running sandbox who have access to the integration.
    Read it before a delete."""
    return affected_user_ids_for_integrations([integration_id], db_session)


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
