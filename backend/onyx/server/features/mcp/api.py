import asyncio
import base64
import datetime
import hashlib
import json
import secrets
import time
from enum import Enum
from typing import cast
from typing import Literal
from urllib.parse import urlencode
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth import PKCEParameters
from mcp.client.auth import TokenStorage
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
)
from mcp.client.auth.utils import build_protected_resource_metadata_discovery_urls
from mcp.client.auth.utils import create_client_info_from_metadata_url
from mcp.client.auth.utils import create_client_registration_request
from mcp.client.auth.utils import create_oauth_metadata_request
from mcp.client.auth.utils import get_client_metadata_scopes
from mcp.client.auth.utils import handle_auth_metadata_response
from mcp.client.auth.utils import handle_protected_resource_response
from mcp.client.auth.utils import handle_registration_response
from mcp.client.auth.utils import should_use_client_metadata_url
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.auth import OAuthMetadata
from mcp.shared.auth import OAuthToken
from mcp.shared.auth import ProtectedResourceMetadata
from mcp.types import InitializeResult
from mcp.types import Tool as MCPLibTool
from pydantic import AnyUrl
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.schemas import UserRole
from onyx.auth.users import current_curator_or_admin_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.db.enums import Permission
from onyx.db.mcp import create_connection_config
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.mcp import delete_all_user_connection_configs_for_server_no_commit
from onyx.db.mcp import delete_connection_config
from onyx.db.mcp import delete_mcp_server
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_all_mcp_servers
from onyx.db.mcp import get_connection_config_by_id
from onyx.db.mcp import get_mcp_server_by_id
from onyx.db.mcp import get_mcp_servers_for_persona
from onyx.db.mcp import get_server_auth_template
from onyx.db.mcp import get_user_connection_config
from onyx.db.mcp import update_connection_config
from onyx.db.mcp import update_mcp_server__no_commit
from onyx.db.mcp import upsert_user_connection_config
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer as DbMCPServer
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.tools import create_tool__no_commit
from onyx.db.tools import delete_tool__no_commit
from onyx.db.tools import get_tools_by_mcp_server_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.mcp.models import apply_auto_substitutions
from onyx.server.features.mcp.models import MCPApiKeyResponse
from onyx.server.features.mcp.models import MCPAuthTemplate
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.server.features.mcp.models import MCPOAuthCallbackResponse
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.models import MCPServer
from onyx.server.features.mcp.models import MCPServerCreateResponse
from onyx.server.features.mcp.models import MCPServerSimpleCreateRequest
from onyx.server.features.mcp.models import MCPServerSimpleUpdateRequest
from onyx.server.features.mcp.models import MCPServersResponse
from onyx.server.features.mcp.models import MCPServerUpdateResponse
from onyx.server.features.mcp.models import MCPToolCreateRequest
from onyx.server.features.mcp.models import MCPToolListResponse
from onyx.server.features.mcp.models import MCPToolUpdateRequest
from onyx.server.features.mcp.models import MCPUserCredentialsRequest
from onyx.server.features.mcp.models import MCPUserOAuthConnectRequest
from onyx.server.features.mcp.models import MCPUserOAuthConnectResponse
from onyx.server.features.tool.models import ToolSnapshot
from onyx.tools.tool_implementations.mcp.mcp_client import discover_mcp_tools
from onyx.tools.tool_implementations.mcp.mcp_client import initialize_mcp_client
from onyx.tools.tool_implementations.mcp.mcp_client import log_exception_group
from onyx.utils.encryption import mask_string
from onyx.utils.encryption import reject_masked_credentials
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _truncate_description(description: str | None, max_length: int = 500) -> str:
    """Truncate description to max_length characters, adding ellipsis if truncated."""
    if not description:
        return ""
    if len(description) <= max_length:
        return description
    return description[: max_length - 3] + "..."


def _resolve_oauth_credentials(
    *,
    request_client_id: str | None,
    request_client_id_changed: bool,
    request_client_secret: str | None,
    request_client_secret_changed: bool,
    existing_client: OAuthClientInformationFull | None,
) -> tuple[str | None, str | None]:
    """Pick the effective client_id / client_secret for an upsert/connect.

    Mirrors the LLM-provider `api_key_changed` pattern: when the frontend
    flags a field as unchanged, ignore whatever value it sent (it is most
    likely a masked placeholder) and reuse the stored value. When the
    frontend flags a field as changed, take the request value as-is, but
    defensively reject masked placeholders so a buggy client can't write
    a mask to the database.

    When there is no stored client yet (`existing_client is None`), an
    unchanged flag means the user did not edit since load — still use the
    request body (`_connect_oauth` runs after upsert with the same payload).
    Treating unchanged plus no storage as None would rebuild empty OAuth config.
    """
    resolved_id = request_client_id
    if not request_client_id_changed:
        resolved_id = (
            existing_client.client_id if existing_client else request_client_id
        )
    elif resolved_id:
        reject_masked_credentials({"oauth_client_id": resolved_id})

    resolved_secret = request_client_secret
    if not request_client_secret_changed:
        resolved_secret = (
            existing_client.client_secret if existing_client else request_client_secret
        )
    elif resolved_secret:
        reject_masked_credentials({"oauth_client_secret": resolved_secret})

    return resolved_id, resolved_secret


def _resolve_admin_credentials(
    *,
    request_credentials: dict[str, str],
    request_credentials_changed: dict[str, bool],
    existing_user_credentials: dict[str, str] | None,
) -> dict[str, str]:
    """Per-key analogue of ``_resolve_oauth_credentials``: reuse the
    stored value when the changed flag is False, otherwise take the
    request value and reject masked placeholders defensively. Stored
    values are sourced from the editing admin's own per-user
    ``header_substitutions``."""
    resolved: dict[str, str] = {}
    for key, request_value in request_credentials.items():
        changed = request_credentials_changed.get(key, False)
        if (
            not changed
            and existing_user_credentials
            and key in existing_user_credentials
        ):
            resolved[key] = existing_user_credentials[key]
            continue
        if request_value:
            reject_masked_credentials({key: request_value})
        resolved[key] = request_value
    return resolved


def _build_oauth_admin_config_data(
    *,
    client_id: str | None,
    client_secret: str | None,
    authorization_url_params: dict[str, str] | None = None,
) -> MCPConnectionData:
    """Construct the admin connection config payload for an OAuth client.

    A public client legitimately has no `client_secret`, so we only require
    a `client_id` to seed `client_info`. When no client_id is available we
    fall through to an empty config (the OAuth provider will rely on
    Dynamic Client Registration to obtain credentials).
    """
    config_data = MCPConnectionData(headers={})
    if authorization_url_params:
        config_data[MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value] = (
            authorization_url_params
        )
    if not client_id:
        return config_data
    token_endpoint_auth_method = "client_secret_post" if client_secret else "none"
    client_info = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=REQUESTED_SCOPE,  # TODO(evan): allow specifying scopes?
        token_endpoint_auth_method=token_endpoint_auth_method,
    )
    config_data[MCPOAuthKeys.CLIENT_INFO.value] = client_info.model_dump(mode="json")
    return config_data


def _build_oauth_admin_config_data_for_update(
    *,
    client_id: str | None,
    client_secret: str | None,
    existing_client: OAuthClientInformationFull,
    authorization_url_params: dict[str, str] | None = None,
) -> MCPConnectionData:
    """Construct the admin connection config payload for an OAuth client
    that already has a stored `client_info`, preserving provider-managed
    fields (DCR registration token, expiry timestamps, negotiated auth
    method, etc.) wherever possible.

    When `client_id` matches the stored client_id, the merged payload
    starts from `existing_client` and only overwrites the admin-managed
    fields (`client_secret`, `redirect_uris`, `scope`). When `client_id`
    differs, the admin is pointing at a brand-new OAuth registration so
    the old DCR metadata is stale; we fall back to the template path.
    """
    if not client_id:
        # No id means we have nothing to seed client_info with; matches
        # the template-path behavior of returning an empty config so the
        # OAuth provider can attempt DCR.
        return _build_oauth_admin_config_data(
            client_id=client_id,
            client_secret=client_secret,
            authorization_url_params=authorization_url_params,
        )

    if existing_client.client_id != client_id:
        logger.info(
            "OAuth client_id changed for existing MCP server; discarding "
            "stored DCR registration metadata and starting fresh."
        )
        return _build_oauth_admin_config_data(
            client_id=client_id,
            client_secret=client_secret,
            authorization_url_params=authorization_url_params,
        )

    merged = existing_client.model_copy(deep=True)
    merged.client_secret = client_secret
    merged.redirect_uris = [AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")]
    merged.scope = REQUESTED_SCOPE  # TODO(evan): allow specifying scopes?
    # Heal stale records that were seeded before `_upsert_mcp_server` always
    # set `token_endpoint_auth_method`. The SDK silently omits the client
    # secret on token exchange when this is None, which manifests as
    # `invalid_client` from the IdP. Preserve any explicitly-negotiated
    # method (e.g. DCR's `client_secret_basic`).
    if merged.token_endpoint_auth_method is None:
        merged.token_endpoint_auth_method = (
            "client_secret_post" if client_secret else "none"
        )

    config_data = MCPConnectionData(headers={})
    if authorization_url_params:
        config_data[MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value] = (
            authorization_url_params
        )
    config_data[MCPOAuthKeys.CLIENT_INFO.value] = merged.model_dump(mode="json")
    return config_data


router = APIRouter(prefix="/mcp")
admin_router = APIRouter(prefix="/admin/mcp")
STATE_TTL_SECONDS = 60 * 5  # 5 minutes
OAUTH_WAIT_SECONDS = 30  # Give the user 30 seconds to complete the OAuth flow
UNUSED_RETURN_PATH = "unused_path"
OAUTH_FLOW_MODE_PROACTIVE = "proactive"
OAUTH_FLOW_MODE_SDK = "sdk"

HEADER_SUBSTITUTIONS: Literal["header_substitutions"] = "header_substitutions"


def key_auth_url(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:auth_url"


def key_state(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:state"


def key_code(user_id: str, state: str) -> str:
    return f"mcp:oauth:{user_id}:{state}:codes"


def key_tokens(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:tokens"


def key_client_info(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:client_info"


def key_pkce_verifier(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:pkce_verifier"


def key_oauth_discovery(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:discovery"


def key_oauth_flow_mode(user_id: str) -> str:
    return f"mcp:oauth:{user_id}:flow_mode"


def _merge_user_oauth_connection_config(
    existing_user_data: MCPConnectionData,
    admin_seed_data: MCPConnectionData,
    *,
    credentials_changed: bool,
) -> MCPConnectionData:
    """Merge admin OAuth client metadata into the per-user row without dropping tokens."""
    merged: MCPConnectionData = MCPConnectionData(headers={})
    merged.update(admin_seed_data)
    if credentials_changed:
        return merged

    existing_tokens = existing_user_data.get(MCPOAuthKeys.TOKENS.value)
    if existing_tokens:
        merged[MCPOAuthKeys.TOKENS.value] = existing_tokens

    existing_headers = existing_user_data.get("headers")
    if isinstance(existing_headers, dict) and existing_headers:
        merged["headers"] = dict(existing_headers)

    return merged


def _set_oauth_flow_mode(user_id: str, mode: str) -> None:
    r = get_redis_client()
    r.set(key_oauth_flow_mode(user_id), mode, ex=STATE_TTL_SECONDS)
    if mode == OAUTH_FLOW_MODE_SDK:
        r.delete(key_pkce_verifier(user_id))


def _oauth_callback_uses_proactive_exchange(user_id: str) -> bool:
    r = get_redis_client()
    mode_raw = r.get(key_oauth_flow_mode(user_id))
    if mode_raw is not None:
        return mode_raw.decode() == OAUTH_FLOW_MODE_PROACTIVE
    # In-flight connects that set PKCE before flow_mode was written.
    return r.get(key_pkce_verifier(user_id)) is not None


def _connection_has_oauth_tokens(connection_config_dict: dict[str, object]) -> bool:
    """True when the user's MCP connection config has stored OAuth tokens.

    Do not infer this from ``client_info`` or ``headers`` alone — some servers
    accept unauthenticated handshake RPCs before any user has completed OAuth.
    """
    return bool(connection_config_dict.get(MCPOAuthKeys.TOKENS.value))


def _oauth_authorization_url_params_changed(
    existing_config_data: MCPConnectionData,
    requested_params: dict[str, str],
) -> bool:
    existing_params = existing_config_data.get(
        MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value, {}
    )
    return existing_params != requested_params


REQUESTED_SCOPE: str | None = None
TOKEN_EXPIRES_AT = "expires_at"
RESERVED_AUTHORIZATION_URL_PARAMS = {
    "client_id",
    "code_challenge",
    "code_challenge_method",
    "redirect_uri",
    "response_type",
    "state",
}


class OnyxTokenStorage(TokenStorage):
    """
    store auth info in a particular user's connection config in postgres
    """

    def __init__(self, connection_config_id: int, alt_config_id: int | None = None):
        self.alt_config_id = alt_config_id
        self.connection_config_id = connection_config_id

    def _ensure_connection_config(self, db_session: Session) -> MCPConnectionConfig:
        config = get_connection_config_by_id(self.connection_config_id, db_session)
        if config is None:
            raise HTTPException(status_code=404, detail="Connection config not found")
        return config

    async def get_tokens(self) -> OAuthToken | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            tokens_raw = config_data.get(MCPOAuthKeys.TOKENS.value)
            if tokens_raw:
                return OAuthToken.model_validate(tokens_raw)
            return None

    async def get_token_expiry_time(self) -> float | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            tokens_raw = config_data.get(MCPOAuthKeys.TOKENS.value)
            if isinstance(tokens_raw, dict):
                expires_at = tokens_raw.get(TOKEN_EXPIRES_AT)
                if isinstance(expires_at, int | float):
                    return max(float(expires_at), 1.0)
                if tokens_raw.get("refresh_token"):
                    return 1.0
            return None

    async def get_authorization_url_params(self) -> dict[str, str]:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            params_raw = config_data.get(MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value)
            if isinstance(params_raw, dict):
                return {
                    str(key): str(value)
                    for key, value in params_raw.items()
                    if key not in RESERVED_AUTHORIZATION_URL_PARAMS
                }

            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                if alt_config:
                    alt_config_data = extract_connection_data(alt_config)
                    alt_params_raw = alt_config_data.get(
                        MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value
                    )
                    if isinstance(alt_params_raw, dict):
                        return {
                            str(key): str(value)
                            for key, value in alt_params_raw.items()
                            if key not in RESERVED_AUTHORIZATION_URL_PARAMS
                        }
            return {}

    async def get_oauth_metadata_context(self) -> dict[str, object] | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            metadata_raw = config_data.get(MCPOAuthKeys.METADATA.value)
            if isinstance(metadata_raw, dict):
                return metadata_raw

            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                if alt_config:
                    alt_config_data = extract_connection_data(alt_config)
                    alt_metadata_raw = alt_config_data.get(MCPOAuthKeys.METADATA.value)
                    if isinstance(alt_metadata_raw, dict):
                        return alt_metadata_raw
            return None

    async def set_oauth_metadata_context(
        self,
        metadata_payload: dict[str, object],
    ) -> None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            config_data[MCPOAuthKeys.METADATA.value] = metadata_payload
            update_connection_config(config.id, db_session, config_data)

            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                if alt_config:
                    alt_config_data = extract_connection_data(alt_config)
                    alt_config_data[MCPOAuthKeys.METADATA.value] = metadata_payload
                    update_connection_config(
                        self.alt_config_id, db_session, alt_config_data
                    )

    async def set_tokens(self, tokens: OAuthToken) -> None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            token_data = tokens.model_dump(mode="json")
            existing_tokens = config_data.get(MCPOAuthKeys.TOKENS.value)
            if (
                isinstance(existing_tokens, dict)
                and existing_tokens.get("refresh_token")
                and not token_data.get("refresh_token")
            ):
                token_data["refresh_token"] = existing_tokens["refresh_token"]
            if tokens.expires_in is not None:
                token_data[TOKEN_EXPIRES_AT] = time.time() + tokens.expires_in
            config_data[MCPOAuthKeys.TOKENS.value] = token_data
            config_data["headers"] = {
                "Authorization": f"{tokens.token_type} {tokens.access_token}"
            }
            update_connection_config(config.id, db_session, config_data)

        # The shared admin row is intentionally NOT written here: it
        # serves as the OAuth `client_info` registry shared across all
        # users of this MCP server (see `get_client_info`). Per-user
        # state (access tokens and resolved `Authorization` headers)
        # belongs only on the per-user row. The Redis push below is
        # what `process_oauth_callback` blocks on to know token exchange
        # has completed; the admin config id is the only stable
        # identifier shared between the two contexts.
        if self.alt_config_id:
            r = get_redis_client()
            r.rpush(key_tokens(str(self.alt_config_id)), tokens.model_dump_json())
            r.expire(key_tokens(str(self.alt_config_id)), OAUTH_WAIT_SECONDS)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            client_info_raw = config_data.get(MCPOAuthKeys.CLIENT_INFO.value)
            if client_info_raw:
                return OAuthClientInformationFull.model_validate(client_info_raw)
            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                if alt_config:
                    alt_config_data = extract_connection_data(alt_config)
                    alt_client_info = alt_config_data.get(
                        MCPOAuthKeys.CLIENT_INFO.value
                    )
                    if alt_client_info:
                        # Cache the admin client info on the user config for future calls
                        config_data[MCPOAuthKeys.CLIENT_INFO.value] = alt_client_info
                        update_connection_config(config.id, db_session, config_data)
                        return OAuthClientInformationFull.model_validate(
                            alt_client_info
                        )
            return None

    async def set_client_info(  # ty: ignore[invalid-method-override]
        self, info: OAuthClientInformationFull
    ) -> None:
        info_payload = info.model_dump(mode="json")
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config_data = extract_connection_data(config)
            config_data[MCPOAuthKeys.CLIENT_INFO.value] = info_payload
            update_connection_config(config.id, db_session, config_data)

            # The shared admin row holds the OAuth `client_info` registry
            # used by every user of this MCP server (see `get_client_info`).
            # When DCR runs we want to cache the discovered client_info there
            # so future users can re-use it — but ONLY the `client_info`
            # field. The per-user `config_data` carries per-user state
            # (`tokens`, resolved `Authorization` header) which belongs
            # only on the per-user row.
            if self.alt_config_id:
                alt_config = get_connection_config_by_id(self.alt_config_id, db_session)
                alt_config_data = extract_connection_data(alt_config)
                alt_config_data[MCPOAuthKeys.CLIENT_INFO.value] = info_payload
                update_connection_config(
                    self.alt_config_id, db_session, alt_config_data
                )


class OnyxOAuthClientProvider(OAuthClientProvider):
    async def _initialize(self) -> None:  # pragma: no cover
        await super()._initialize()
        if isinstance(self.context.storage, OnyxTokenStorage):
            self.context.token_expiry_time = (
                await self.context.storage.get_token_expiry_time()
            )
            metadata = await self.context.storage.get_oauth_metadata_context()
            if metadata:
                self.context.oauth_metadata = OAuthMetadata.model_validate(
                    metadata["oauth_metadata"]
                )
                self.context.auth_server_url = metadata.get("auth_server_url")
                prm_raw = metadata.get("protected_resource_metadata")
                if prm_raw:
                    self.context.protected_resource_metadata = (
                        ProtectedResourceMetadata.model_validate(prm_raw)
                    )
                self.context.client_metadata.scope = get_client_metadata_scopes(
                    None,
                    self.context.protected_resource_metadata,
                    self.context.oauth_metadata,
                )
            elif (
                self.context.current_tokens
                and self.context.current_tokens.refresh_token
            ):
                try:
                    await _discover_oauth_metadata_for_connect(
                        self, self.context.server_url
                    )
                except Exception:
                    logger.debug(
                        "Could not discover MCP OAuth metadata while hydrating provider",
                        exc_info=True,
                    )


def make_oauth_provider(
    mcp_server: DbMCPServer,
    user_id: str,
    return_path: str,
    connection_config_id: int,
    admin_config_id: int | None,
) -> OAuthClientProvider:
    async def redirect_handler(auth_url: str) -> None:
        if return_path == UNUSED_RETURN_PATH:
            raise ValueError("Please Reconnect to the server")
        r = get_redis_client()
        # The SDK generated & embedded 'state' in the auth_url; extract & store it.
        parsed = urlparse(auth_url)
        qs = dict([p.split("=", 1) for p in parsed.query.split("&") if "=" in p])
        state = qs.get("state")
        if not state:
            # Defensive: some providers encode state differently; adapt if needed.
            raise RuntimeError("Missing state in authorization_url")

        # Save for the frontend & for callback validation
        state_obj = MCPOauthState(
            server_id=mcp_server.id,
            return_path=return_path,
            is_admin=admin_config_id is not None,
            state=state,
        )
        # Persist callback state before the auth URL is visible to the connect waiter.
        r.set(key_state(user_id), state_obj.model_dump_json(), ex=STATE_TTL_SECONDS)
        r.rpush(key_auth_url(user_id), auth_url)
        r.expire(key_auth_url(user_id), OAUTH_WAIT_SECONDS)

        # Return immediately; the HTTP layer will read the stored URL and send it to the browser.

    async def callback_handler() -> tuple[str, str | None]:
        r = get_redis_client()
        # Wait up to TTL for the code published by the /oauth/callback route
        state = r.get(key_state(user_id))
        if not state:
            raise RuntimeError("No pending OAuth state for user")
        state_obj = MCPOauthState.model_validate_json(state)

        # Block on Redis for (code, state). BLPOP returns (key, value).
        key = key_code(user_id, state_obj.state)

        # requests CAN block here for up to a minute if the user doesn't resolve the OAuth flow
        # Run the blocking blpop operation in a thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        pop = await loop.run_in_executor(
            None, lambda: r.blpop([key], timeout=OAUTH_WAIT_SECONDS)
        )
        # TODO: gracefully handle "user says no"
        if not pop:
            raise RuntimeError("Timed out waiting for OAuth callback")

        code_state_dict = json.loads(pop[1].decode())

        code = code_state_dict["code"]

        if code_state_dict["state"] != state_obj.state:
            raise RuntimeError("Invalid state in OAuth callback")

        # Optional: cleanup
        r.delete(key_auth_url(user_id), key_state(user_id))
        return code, state_obj.state

    return OnyxOAuthClientProvider(
        server_url=mcp_server.server_url,
        client_metadata=OAuthClientMetadata(
            client_name=f"Onyx - {mcp_server.name}",
            redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=REQUESTED_SCOPE,  # TODO: do we need to pass this in? maybe make configurable
        ),
        storage=OnyxTokenStorage(connection_config_id, admin_config_id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


async def _discover_oauth_metadata_for_connect(
    oauth_provider: OAuthClientProvider,
    server_url: str,
) -> None:
    """Discover protected-resource and authorization-server metadata for MCP OAuth.

    Remote servers such as Google Cloud MCP may allow unauthenticated handshake
    RPCs and return 403 (without WWW-Authenticate) on tool calls, so the MCP SDK
    auth flow never starts. Proactive discovery avoids relying on HTTP 401.
    """
    ctx = oauth_provider.context
    async with httpx.AsyncClient() as client:
        for url in build_protected_resource_metadata_discovery_urls(None, server_url):
            resp = await client.send(create_oauth_metadata_request(url))
            prm = await handle_protected_resource_response(resp)
            if prm:
                ctx.protected_resource_metadata = prm
                if prm.authorization_servers:
                    ctx.auth_server_url = str(prm.authorization_servers[0])
                break

        if not ctx.auth_server_url:
            raise OAuthFlowError(
                f"Could not discover OAuth protected resource metadata for {server_url}"
            )

        for url in build_oauth_authorization_server_metadata_discovery_urls(
            ctx.auth_server_url, server_url
        ):
            resp = await client.send(create_oauth_metadata_request(url))
            ok, asm = await handle_auth_metadata_response(resp)
            if ok and asm:
                ctx.oauth_metadata = asm
                break

        if not ctx.oauth_metadata:
            raise OAuthFlowError(
                f"Could not discover OAuth authorization server metadata for {server_url}"
            )

        ctx.client_metadata.scope = get_client_metadata_scopes(
            None,
            ctx.protected_resource_metadata,
            ctx.oauth_metadata,
        )
        if isinstance(ctx.storage, OnyxTokenStorage):
            await ctx.storage.set_oauth_metadata_context(
                _oauth_metadata_context_payload(oauth_provider)
            )


def _oauth_metadata_context_payload(
    oauth_provider: OAuthClientProvider,
) -> dict[str, object]:
    ctx = oauth_provider.context
    if ctx.oauth_metadata is None:
        raise OAuthFlowError("No OAuth metadata discovered for MCP server")
    payload: dict[str, object] = {
        "oauth_metadata": ctx.oauth_metadata.model_dump(mode="json"),
        "auth_server_url": ctx.auth_server_url,
    }
    if ctx.protected_resource_metadata is not None:
        payload["protected_resource_metadata"] = (
            ctx.protected_resource_metadata.model_dump(mode="json")
        )
    return payload


def _cache_oauth_discovery_context(
    oauth_provider: OAuthClientProvider,
    user_id: str,
) -> None:
    """Persist discovered metadata for the callback route to exchange tokens."""
    ctx = oauth_provider.context
    if ctx.oauth_metadata is None:
        return
    payload = _oauth_metadata_context_payload(oauth_provider)
    get_redis_client().set(
        key_oauth_discovery(user_id),
        json.dumps(payload),
        ex=STATE_TTL_SECONDS,
    )


async def _restore_oauth_discovery_context_async(
    oauth_provider: OAuthClientProvider,
    user_id: str,
    server_url: str,
) -> None:
    cached = get_redis_client().get(key_oauth_discovery(user_id))
    ctx = oauth_provider.context
    if cached:
        data = json.loads(cached)
        ctx.oauth_metadata = OAuthMetadata.model_validate(data["oauth_metadata"])
        ctx.auth_server_url = data.get("auth_server_url")
        prm_raw = data.get("protected_resource_metadata")
        if prm_raw:
            ctx.protected_resource_metadata = ProtectedResourceMetadata.model_validate(
                prm_raw
            )
        ctx.client_metadata.scope = get_client_metadata_scopes(
            None,
            ctx.protected_resource_metadata,
            ctx.oauth_metadata,
        )
        return
    await _discover_oauth_metadata_for_connect(oauth_provider, server_url)


async def _complete_oauth_token_exchange_from_callback(
    oauth_provider: OAuthClientProvider,
    server_url: str,
    user_id: str,
    code: str,
    state: str,
) -> None:
    """Exchange the authorization code for tokens in the callback HTTP handler.

    Proactive connect returns the IdP URL without running the MCP SDK's HTTP 401
    auth flow, so this handler must finish what ``async_auth_flow`` would normally
    do after the browser redirect. We intentionally call MCP SDK private methods
    (``_initialize``, ``_exchange_token_authorization_code``, ``_handle_token_response``)
    because there is no public "exchange code only" API; they load stored client
    metadata, build the token request (including PKCE), and persist tokens via
    ``OnyxTokenStorage``.
    """
    await oauth_provider._initialize()
    await _restore_oauth_discovery_context_async(
        oauth_provider, user_id, server_url
    )

    stored_state = get_redis_client().get(key_state(user_id))
    if not stored_state:
        raise OAuthFlowError("No pending OAuth state for user")
    state_obj = MCPOauthState.model_validate_json(stored_state)
    if not secrets.compare_digest(state, state_obj.state):
        raise OAuthFlowError("OAuth state parameter mismatch")

    verifier_raw = get_redis_client().get(key_pkce_verifier(user_id))
    if not verifier_raw:
        raise OAuthFlowError("Missing PKCE verifier for OAuth token exchange")

    token_request = await oauth_provider._exchange_token_authorization_code(
        code, verifier_raw.decode()
    )
    async with httpx.AsyncClient() as client:
        token_response = await client.send(token_request)
        await oauth_provider._handle_token_response(token_response)

    r = get_redis_client()
    r.delete(
        key_state(user_id),
        key_auth_url(user_id),
        key_pkce_verifier(user_id),
        key_oauth_discovery(user_id),
        key_oauth_flow_mode(user_id),
        key_code(user_id, state),
    )


async def _complete_oauth_callback_legacy_sdk_path(
    user_id: str,
    state: str,
    code: str,
    admin_config_id: int,
) -> None:
    """Original callback path for MCP servers that drive OAuth via HTTP 401 + SDK.

    Unblocks ``callback_handler`` on an in-flight ``initialize_mcp_client`` task and
    waits for ``OnyxTokenStorage.set_tokens`` to publish the exchanged tokens.
    """
    r = get_redis_client()
    r.rpush(key_code(user_id, state), json.dumps({"code": code, "state": state}))
    r.expire(key_code(user_id, state), OAUTH_WAIT_SECONDS)

    loop = asyncio.get_running_loop()
    tokens_raw = await loop.run_in_executor(
        None,
        lambda: r.blpop([key_tokens(str(admin_config_id))], timeout=OAUTH_WAIT_SECONDS),
    )
    if tokens_raw is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "No tokens found")
    tokens = OAuthToken.model_validate_json(tokens_raw[1].decode())
    if not tokens.access_token:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "No access_token in OAuth response"
        )


async def _ensure_oauth_client_registered(
    oauth_provider: OAuthClientProvider,
) -> None:
    """Register an OAuth client when proactive connect has metadata but no client_id."""
    await oauth_provider._initialize()
    ctx = oauth_provider.context
    if ctx.client_info and ctx.client_info.client_id:
        return

    if should_use_client_metadata_url(ctx.oauth_metadata, ctx.client_metadata_url):
        client_information = create_client_info_from_metadata_url(
            ctx.client_metadata_url,  # type: ignore[arg-type]
            redirect_uris=ctx.client_metadata.redirect_uris,
        )
        ctx.client_info = client_information
        await ctx.storage.set_client_info(client_information)
        return

    registration_request = create_client_registration_request(
        ctx.oauth_metadata,
        ctx.client_metadata,
        ctx.get_authorization_base_url(ctx.server_url),
    )
    async with httpx.AsyncClient() as client:
        registration_response = await client.send(registration_request)
    try:
        client_information = await handle_registration_response(registration_response)
    except Exception as e:
        raise OAuthFlowError(f"Dynamic client registration failed: {e}") from e

    ctx.client_info = client_information
    await ctx.storage.set_client_info(client_information)


async def _publish_oauth_authorization_url(
    oauth_provider: OAuthClientProvider,
    user_id: str,
) -> None:
    """Build the browser authorization URL and publish it via ``redirect_handler``."""
    ctx = oauth_provider.context
    if ctx.client_metadata.redirect_uris is None:
        raise OAuthFlowError("No redirect URIs configured for MCP OAuth")
    if not ctx.redirect_handler:
        raise OAuthFlowError("No redirect handler configured for MCP OAuth")
    if not ctx.client_info or not ctx.client_info.client_id:
        raise OAuthFlowError("No OAuth client ID configured for MCP server")

    if ctx.oauth_metadata and ctx.oauth_metadata.authorization_endpoint:
        auth_endpoint = str(ctx.oauth_metadata.authorization_endpoint)
    else:
        auth_base_url = ctx.get_authorization_base_url(ctx.server_url)
        auth_endpoint = f"{auth_base_url.rstrip('/')}/authorize"

    pkce_params = PKCEParameters.generate()
    get_redis_client().set(
        key_pkce_verifier(user_id),
        pkce_params.code_verifier,
        ex=STATE_TTL_SECONDS,
    )

    auth_params: dict[str, str] = {
        "response_type": "code",
        "client_id": ctx.client_info.client_id,
        "redirect_uri": str(ctx.client_metadata.redirect_uris[0]),
        "state": secrets.token_urlsafe(32),
        "code_challenge": pkce_params.code_challenge,
        "code_challenge_method": "S256",
    }
    if ctx.should_include_resource_param(ctx.protocol_version):
        auth_params["resource"] = ctx.get_resource_url()
    if ctx.client_metadata.scope:
        auth_params["scope"] = ctx.client_metadata.scope
    if isinstance(ctx.storage, OnyxTokenStorage):
        auth_params.update(await ctx.storage.get_authorization_url_params())

    authorization_url = f"{auth_endpoint}?{urlencode(auth_params)}"
    await ctx.redirect_handler(authorization_url)


async def _start_proactive_user_oauth(
    oauth_provider: OAuthClientProvider,
    server_url: str,
    user_id: str,
) -> None:
    """Discover OAuth metadata, register client if needed, publish the IdP URL."""
    await oauth_provider._initialize()
    await _discover_oauth_metadata_for_connect(oauth_provider, server_url)
    _cache_oauth_discovery_context(oauth_provider, user_id)
    await _ensure_oauth_client_registered(oauth_provider)
    _set_oauth_flow_mode(user_id, OAUTH_FLOW_MODE_PROACTIVE)
    await _publish_oauth_authorization_url(oauth_provider, user_id)


def _log_sdk_oauth_init_task_done(task: asyncio.Task[InitializeResult]) -> None:
    """Log failures from the SDK OAuth initialize task left alive for callback."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("SDK OAuth initialize task failed after auth URL was returned")


async def _await_sdk_oauth_auth_url(
    *,
    probe_url: str,
    connection_headers: dict[str, str],
    transport: MCPTransport,
    oauth_auth: OAuthClientProvider,
    user_id: str,
) -> str:
    """Fall back to the MCP SDK 401/WWW-Authenticate OAuth path for the auth URL.

    The initialize task must stay alive after returning the auth URL so the SDK
    ``callback_handler`` can receive the browser code and complete token exchange.
    """
    _set_oauth_flow_mode(user_id, OAUTH_FLOW_MODE_SDK)
    init_task = asyncio.create_task(
        initialize_mcp_client(
            probe_url,
            connection_headers=connection_headers,
            transport=transport,
            auth=oauth_auth,
        )
    )
    r = get_redis_client()
    loop = asyncio.get_running_loop()
    try:
        raw = await loop.run_in_executor(
            None,
            lambda: r.blpop([key_auth_url(user_id)], timeout=OAUTH_WAIT_SECONDS),
        )
        if raw is None:
            init_task.cancel()
            try:
                await init_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug(
                    "SDK OAuth initialize task ended after auth URL timeout",
                    exc_info=True,
                )
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Auth URL retrieval timed out"
            )
        init_task.add_done_callback(_log_sdk_oauth_init_task_done)
        return raw[1].decode()
    except OnyxError:
        raise
    except Exception:
        init_task.cancel()
        try:
            await init_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug(
                "SDK OAuth initialize task ended after auth URL failure",
                exc_info=True,
            )
        raise


async def _await_oauth_auth_url_for_connect(
    user_id: str,
    publish_task: asyncio.Task[None],
) -> str:
    """Poll Redis for an auth URL until proactive publish succeeds or fails."""
    r = get_redis_client()
    loop = asyncio.get_running_loop()
    deadline = time.monotonic() + OAUTH_WAIT_SECONDS
    poll_seconds = 2

    while time.monotonic() < deadline:
        if publish_task.done():
            publish_exc = publish_task.exception()
            if publish_exc is not None:
                raise publish_exc

        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            break
        block_seconds = min(poll_seconds, remaining)
        raw = await loop.run_in_executor(
            None,
            lambda timeout=block_seconds: r.blpop(
                [key_auth_url(user_id)], timeout=timeout
            ),
        )
        if raw is not None:
            return raw[1].decode()

    if publish_task.done():
        publish_exc = publish_task.exception()
        if publish_exc is not None:
            raise publish_exc
    raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Auth URL retrieval timed out")


async def _await_publish_task_after_auth_url(publish_task: asyncio.Task[None]) -> None:
    """Let the OAuth publisher finish after the auth URL is already visible."""
    if publish_task.done():
        publish_exc = publish_task.exception()
        if publish_exc is not None:
            logger.debug(
                "OAuth publisher finished with error after auth URL was returned: %s",
                publish_exc,
            )
        return
    try:
        await publish_task
    except asyncio.CancelledError:
        pass
    except Exception as publish_exc:
        logger.debug(
            "OAuth publisher ended after auth URL was returned: %s",
            publish_exc,
        )


async def _connect_oauth_without_tokens(
    *,
    oauth_auth: OAuthClientProvider,
    probe_url: str,
    connection_headers: dict[str, str],
    transport: MCPTransport,
    user_id: str,
    mcp_server_name: str,
) -> str:
    """Start OAuth for a user without stored tokens; return the browser auth URL."""
    publish_task = asyncio.create_task(
        _start_proactive_user_oauth(oauth_auth, probe_url, user_id)
    )
    auth_task = asyncio.create_task(
        _await_oauth_auth_url_for_connect(user_id, publish_task)
    )

    done, _pending = await asyncio.wait(
        [auth_task, publish_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if publish_task in done and publish_task.exception() is not None:
        auth_task.cancel()
        try:
            await auth_task
        except (asyncio.CancelledError, Exception):
            pass
        publish_exc = publish_task.exception()
        assert publish_exc is not None
        logger.warning(
            "Proactive OAuth failed for server %s, falling back to SDK 401 flow: %s",
            mcp_server_name,
            publish_exc,
        )
        try:
            return await _await_sdk_oauth_auth_url(
                probe_url=probe_url,
                connection_headers=connection_headers,
                transport=transport,
                oauth_auth=oauth_auth,
                user_id=user_id,
            )
        except OnyxError:
            raise
        except Exception as sdk_exc:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                (
                    f"Failed to start OAuth authorization: {publish_exc}. "
                    f"SDK fallback also failed: {sdk_exc}"
                ),
            ) from sdk_exc

    if auth_task in done:
        try:
            oauth_url = auth_task.result()
        except BaseException:
            publish_task.cancel()
            try:
                await publish_task
            except (asyncio.CancelledError, Exception):
                pass
            raise
        await _await_publish_task_after_auth_url(publish_task)
        return oauth_url

    oauth_url = await auth_task
    await _await_publish_task_after_auth_url(publish_task)
    return oauth_url


def _build_headers_from_template(
    template_data: MCPAuthTemplate, credentials: dict[str, str], user_email: str
) -> dict[str, str]:
    """Build headers dict from template and credentials"""
    headers = {}
    template_headers = template_data.headers

    for name, value_template in template_headers.items():
        value = value_template
        for key, cred_value in credentials.items():
            value = value.replace(f"{{{key}}}", cred_value)
        value = apply_auto_substitutions(value, user_email=user_email)

        if name:
            headers[name] = value

    return headers


def test_mcp_server_credentials(
    server_url: str,
    connection_headers: dict[str, str] | None,
    auth: OAuthClientProvider | None,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
) -> tuple[bool, str]:
    """Test if credentials work by calling the MCP server's tools/list endpoint"""
    try:
        # Attempt to discover tools using the provided credentials
        tools = discover_mcp_tools(
            server_url, connection_headers, transport=transport, auth=auth
        )

        if (
            tools is not None and len(tools) >= 0
        ):  # Even 0 tools is a successful connection
            return True, f"Successfully connected. Found {len(tools)} tools."
        else:
            return False, "Failed to retrieve tools list from server."

    except Exception as e:
        logger.error("Failed to test MCP server credentials: %s", e)
        return False, f"Connection failed: {str(e)}"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_urlsafe(64).encode())
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class MCPOauthState(BaseModel):
    server_id: int
    return_path: str
    is_admin: bool
    state: str


@admin_router.post("/oauth/connect", response_model=MCPUserOAuthConnectResponse)
async def connect_admin_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPUserOAuthConnectResponse:
    """Connect OAuth flow for admin MCP server authentication"""
    return await _connect_oauth(request, db, is_admin=True, user=user)


@router.post("/oauth/connect", response_model=MCPUserOAuthConnectResponse)
async def connect_user_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPUserOAuthConnectResponse:
    return await _connect_oauth(request, db, is_admin=False, user=user)


async def _connect_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session,
    is_admin: bool,
    user: User,
) -> MCPUserOAuthConnectResponse:
    """Connect OAuth flow for per-user MCP server authentication"""

    logger.info("Initiating per-user OAuth for server: %s", request.server_id)

    try:
        server_id = int(request.server_id)
        mcp_server = get_mcp_server_by_id(server_id, db)
    except Exception:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if is_admin:
        _ensure_mcp_server_owner_or_admin(mcp_server, user)

    if mcp_server.auth_type != MCPAuthenticationType.OAUTH:
        auth_type_str = mcp_server.auth_type.value if mcp_server.auth_type else "None"
        raise HTTPException(
            status_code=400,
            detail=f"Server was configured with authentication type {auth_type_str}",
        )

    # Resolve the effective OAuth credentials, falling back to the stored
    # values for any field the frontend marked as unchanged. This protects
    # against the resubmit case where the form replays masked placeholders.
    existing_client: OAuthClientInformationFull | None = None
    existing_data: MCPConnectionData = MCPConnectionData(headers={})
    if mcp_server.admin_connection_config:
        existing_data = extract_connection_data(
            mcp_server.admin_connection_config, apply_mask=False
        )
        existing_client_raw = existing_data.get(MCPOAuthKeys.CLIENT_INFO.value)
        if existing_client_raw:
            existing_client = OAuthClientInformationFull.model_validate(
                existing_client_raw
            )

    request.oauth_client_id, request.oauth_client_secret = _resolve_oauth_credentials(
        request_client_id=request.oauth_client_id,
        request_client_id_changed=request.oauth_client_id_changed,
        request_client_secret=request.oauth_client_secret,
        request_client_secret_changed=request.oauth_client_secret_changed,
        existing_client=existing_client,
    )

    authorization_url_params = request.oauth_authorization_url_params
    if (
        not authorization_url_params
        and MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value in existing_data
    ):
        existing_params = existing_data[MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value]
        if isinstance(existing_params, dict):
            authorization_url_params = {
                str(key): str(value) for key, value in existing_params.items()
            }

    # When we already have a stored `client_info`, merge into it so we
    # preserve any provider-managed fields (DCR registration token,
    # `client_secret_expires_at`, negotiated `token_endpoint_auth_method`,
    # etc.) that the hardcoded template would otherwise drop.
    config_data = (
        _build_oauth_admin_config_data_for_update(
            client_id=request.oauth_client_id,
            client_secret=request.oauth_client_secret,
            existing_client=existing_client,
            authorization_url_params=authorization_url_params,
        )
        if existing_client is not None
        else _build_oauth_admin_config_data(
            client_id=request.oauth_client_id,
            client_secret=request.oauth_client_secret,
            authorization_url_params=authorization_url_params,
        )
    )

    if mcp_server.admin_connection_config_id is None:
        if not is_admin:
            raise HTTPException(
                status_code=400,
                detail="Admin connection config not found for this server",
            )

        admin_config = create_connection_config(
            config_data=config_data,
            mcp_server_id=mcp_server.id,
            user_email="",
            db_session=db,
        )
        mcp_server.admin_connection_config = admin_config
        mcp_server.admin_connection_config_id = (
            admin_config.id
        )  # might not have to do this
    elif is_admin:  # only update admin config if we're an admin
        update_connection_config(mcp_server.admin_connection_config_id, db, config_data)

    connection_config = get_user_connection_config(mcp_server.id, user.email, db)
    existing_user_data: MCPConnectionData = MCPConnectionData(headers={})
    if connection_config is not None:
        existing_user_data = extract_connection_data(
            connection_config, apply_mask=False
        )

    credentials_changed = (
        request.oauth_client_id_changed or request.oauth_client_secret_changed
    )

    if connection_config is None:
        connection_config = create_connection_config(
            config_data=config_data,
            mcp_server_id=mcp_server.id,
            user_email=user.email,
            db_session=db,
        )
        connection_config_dict = extract_connection_data(
            connection_config, apply_mask=False
        )
    else:
        merged_user_config = _merge_user_oauth_connection_config(
            existing_user_data,
            config_data,
            credentials_changed=credentials_changed,
        )
        update_connection_config(connection_config.id, db, merged_user_config)
        connection_config_dict = merged_user_config

    db.commit()

    has_oauth_tokens = _connection_has_oauth_tokens(connection_config_dict)

    if mcp_server.transport is None:
        raise HTTPException(
            status_code=400,
            detail="MCP server transport is not configured",
        )

    transport = (
        mcp_server.transport if has_oauth_tokens else MCPTransport.STREAMABLE_HTTP
    )
    probe_url = mcp_server.server_url
    logger.info("Probing OAuth server at: %s", probe_url)

    oauth_auth = make_oauth_provider(
        mcp_server,
        str(user.id),
        request.return_path,
        connection_config.id,
        mcp_server.admin_connection_config_id,
    )

    user_id_str = str(user.id)

    if not has_oauth_tokens:
        try:
            oauth_url = await _connect_oauth_without_tokens(
                oauth_auth=oauth_auth,
                probe_url=probe_url,
                connection_headers=connection_config_dict.get("headers", {}),
                transport=transport,
                user_id=user_id_str,
                mcp_server_name=mcp_server.name,
            )
        except OnyxError:
            raise
        except Exception as e:
            if isinstance(e, ExceptionGroup):
                saved_e = log_exception_group(e)
            else:
                saved_e = e
            logger.error("OAuth connect failed: %s", saved_e)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to start OAuth authorization: {saved_e}",
            ) from e

        logger.info(
            "Connected to auth url: %s for mcp server: %s", oauth_url, mcp_server.name
        )
        return MCPUserOAuthConnectResponse(
            server_id=int(request.server_id), oauth_url=oauth_url
        )

    try:
        init_result = await initialize_mcp_client(
            probe_url,
            connection_headers=connection_config_dict.get("headers", {}),
            transport=transport,
            auth=oauth_auth,
        )
        logger.info("OAuth connect completed with existing tokens: %s", init_result)
        return MCPUserOAuthConnectResponse(
            server_id=int(request.server_id),
            oauth_url=request.return_path,
        )
    except Exception as e:
        if isinstance(e, ExceptionGroup):
            saved_e = log_exception_group(e)
        else:
            saved_e = e
        logger.error("OAuth initialization failed: %s", saved_e)
        raise HTTPException(
            status_code=400, detail=f"Failed to initialize OAuth client: {str(saved_e)}"
        ) from e


@router.post("/oauth/callback", response_model=MCPOAuthCallbackResponse)
async def process_oauth_callback(
    request: Request,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPOAuthCallbackResponse:
    """Complete OAuth flow by exchanging code for tokens and storing them.

    Notes:
    - For demo/test servers (like run_mcp_server_oauth.py), the token endpoint
      and parameters may be fixed. In production, use the server's metadata
      (e.g., well-known endpoints) to discover token URL and scopes.
    """

    # Get callback data from query parameters (like federated OAuth does)
    callback_data = dict(request.query_params)

    redis_client = get_redis_client()
    state = callback_data.get("state")
    code = callback_data.get("code")
    user_id = str(user.id)
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code parameter")
    stored_data = cast(bytes, redis_client.get(key_state(user_id)))
    if not stored_data:
        raise HTTPException(
            status_code=400, detail="Invalid or expired state parameter"
        )
    state_data = MCPOauthState.model_validate_json(stored_data)
    try:
        server_id = state_data.server_id
        mcp_server = get_mcp_server_by_id(server_id, db_session)
    except Exception:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if mcp_server.admin_connection_config is None:
        raise HTTPException(
            status_code=400,
            detail="Server referenced by callback is not configured, try recreating",
        )

    connection_config = get_user_connection_config(
        mcp_server.id, user.email, db_session
    )
    if connection_config is None:
        raise HTTPException(
            status_code=400,
            detail="User connection config not found for this MCP server",
        )

    oauth_auth = make_oauth_provider(
        mcp_server,
        user_id,
        state_data.return_path,
        connection_config.id,
        mcp_server.admin_connection_config_id,
    )

    if mcp_server.server_url is None:
        raise HTTPException(status_code=400, detail="MCP server URL is not configured")

    admin_config_id = mcp_server.admin_connection_config_id
    if admin_config_id is None:
        raise HTTPException(
            status_code=400,
            detail="Server admin config ID is missing; try recreating the server",
        )

    if _oauth_callback_uses_proactive_exchange(user_id):
        try:
            await _complete_oauth_token_exchange_from_callback(
                oauth_auth,
                mcp_server.server_url,
                user_id,
                code,
                state,
            )
        except OAuthFlowError as e:
            logger.error("MCP OAuth token exchange failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail=f"OAuth token exchange failed: {e}",
            )
        except Exception as e:
            logger.exception("MCP OAuth token exchange failed")
            raise HTTPException(
                status_code=400,
                detail=f"OAuth token exchange failed: {e}",
            )
    else:
        await _complete_oauth_callback_legacy_sdk_path(
            user_id, state, code, admin_config_id
        )

    db_session.commit()

    logger.info(
        "server_id=%s server_name=%s return_path=%s",
        str(mcp_server.id),
        mcp_server.name,
        state_data.return_path,
    )

    return MCPOAuthCallbackResponse(
        success=True,
        server_id=mcp_server.id,
        server_name=mcp_server.name,
        message=f"OAuth authorization completed successfully for {mcp_server.name}",
        redirect_url=state_data.return_path,
    )


@router.post("/user-credentials", response_model=MCPApiKeyResponse)
def save_user_credentials(
    request: MCPUserCredentialsRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPApiKeyResponse:
    """Save user credentials for template-based MCP server authentication"""

    logger.info("Saving user credentials for server: %s", request.server_id)

    try:
        server_id = request.server_id
        mcp_server = get_mcp_server_by_id(server_id, db_session)
    except Exception:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if mcp_server.auth_type == "none":
        raise HTTPException(
            status_code=400,
            detail="Server does not require authentication",
        )

    email = user.email

    # Get the authentication template for this server
    auth_template = get_server_auth_template(server_id, db_session)
    if not auth_template:
        # Fallback to simple API key storage for servers without templates
        if "api_key" not in request.credentials:
            raise HTTPException(
                status_code=400,
                detail="No authentication template found and no api_key provided",
            )
        config_data = MCPConnectionData(
            headers={"Authorization": f"Bearer {request.credentials['api_key']}"},
        )
    else:
        # Render via the shared helper so user + auto (`{user_email}`)
        # substitutions go through one pipeline.
        try:
            # TODO: fix and/or type correctly w/base model
            auth_template_dict = extract_connection_data(
                auth_template, apply_mask=False
            )
            template = MCPAuthTemplate(headers=auth_template_dict.get("headers", {}))
            config_data = MCPConnectionData(
                headers=_build_headers_from_template(
                    template, request.credentials, email
                ),
                header_substitutions=request.credentials,
            )
            for oauth_field_key in MCPOAuthKeys:
                field_key: Literal["client_info", "tokens", "metadata"] = (
                    oauth_field_key.value
                )
                if field_val := auth_template_dict.get(field_key):
                    config_data[field_key] = field_val

        except Exception as e:
            logger.error("Failed to process authentication template: %s", e)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to process authentication template: {str(e)}",
            )

    # Test the credentials before saving
    validation_tested = False
    validation_message = "Credentials saved successfully"

    try:
        auth = None
        if mcp_server.auth_type == MCPAuthenticationType.OAUTH:
            # should only be saving user creds if an admin config exists
            admin_config_id = mcp_server.admin_connection_config_id
            if admin_config_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Server admin config ID is missing; try recreating the server",
                )
            auth = make_oauth_provider(
                mcp_server,
                email,
                UNUSED_RETURN_PATH,
                admin_config_id,
                None,
            )

        server_url = mcp_server.server_url
        is_valid, test_message = test_mcp_server_credentials(
            server_url,
            config_data["headers"],
            transport=MCPTransport(request.transport.replace("-", "_").upper()),
            auth=auth,
        )
        validation_tested = True

        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Credentials validation failed: {test_message}",
            )
        else:
            validation_message = (
                f"Credentials saved and validated successfully. {test_message}"
            )

    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.warning(
            "Could not validate credentials for server %s: %s", mcp_server.name, e
        )
        validation_message = "Credentials saved but could not be validated"

    try:
        # Save the processed credentials
        upsert_user_connection_config(
            server_id=server_id,
            user_email=email,
            config_data=config_data,
            db_session=db_session,
        )

        logger.info(
            "User credentials saved for server %s and user %s", mcp_server.name, email
        )
        db_session.commit()

        return MCPApiKeyResponse(
            success=True,
            message=validation_message,
            server_id=request.server_id,
            server_name=mcp_server.name,
            authenticated=True,
            validation_tested=validation_tested,
        )

    except Exception as e:
        logger.error("Failed to save user credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save user credentials")


class MCPToolDescription(BaseModel):
    id: int
    name: str
    display_name: str
    description: str


class ServerToolsResponse(BaseModel):
    server_id: int
    server_name: str
    server_url: str
    tools: list[MCPToolDescription]


def _ensure_mcp_server_owner_or_admin(server: DbMCPServer, user: User) -> None:
    logger.info(
        "Ensuring MCP server owner or admin: %s %s %s server.owner=%s",
        server.name,
        user,
        user.role,
        server.owner,
    )
    if user.role == UserRole.ADMIN:
        return

    logger.info("User email: %s server.owner=%s", user.email, server.owner)
    if server.owner != user.email:
        raise HTTPException(
            status_code=403,
            detail="Curators can only modify MCP servers that they have created.",
        )


def _db_mcp_server_to_api_mcp_server(
    db_server: DbMCPServer,
    db: Session,
    request_user: User | None,
    include_auth_config: bool = False,
) -> MCPServer:
    """Convert database MCP server to API model"""

    email = request_user.email if request_user else ""

    # Check if user has authentication configured and extract credentials
    auth_performer = db_server.auth_performer
    user_authenticated: bool | None = None
    user_credentials = None
    admin_credentials = None
    oauth_authorization_url_params: dict[str, str] = {}
    can_view_admin_credentials = bool(include_auth_config) and (
        request_user is not None
        and (
            request_user.role == UserRole.ADMIN
            or (request_user.email and request_user.email == db_server.owner)
        )
    )
    if db_server.auth_type == MCPAuthenticationType.NONE:
        user_authenticated = True  # No auth required
    elif auth_performer == MCPAuthenticationPerformer.ADMIN:
        user_authenticated = db_server.admin_connection_config is not None
        if (
            can_view_admin_credentials
            and db_server.admin_connection_config is not None
            and include_auth_config
        ):
            admin_config_dict = extract_connection_data(
                db_server.admin_connection_config, apply_mask=False
            )
            if db_server.auth_type == MCPAuthenticationType.API_TOKEN:
                raw_api_key = admin_config_dict["headers"]["Authorization"].split(" ")[
                    -1
                ]
                admin_credentials = {
                    "api_key": mask_string(raw_api_key),
                }
            elif db_server.auth_type == MCPAuthenticationType.OAUTH:
                user_authenticated = False
                client_info = None
                client_info_raw = admin_config_dict.get(MCPOAuthKeys.CLIENT_INFO.value)
                params_raw = admin_config_dict.get(
                    MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value
                )
                if isinstance(params_raw, dict):
                    oauth_authorization_url_params = {
                        str(key): str(value) for key, value in params_raw.items()
                    }
                if client_info_raw:
                    client_info = OAuthClientInformationFull.model_validate(
                        client_info_raw
                    )
                if client_info:
                    if not client_info.client_id:
                        raise ValueError("Stored client info had empty client ID")
                    admin_credentials = {
                        "client_id": mask_string(client_info.client_id),
                    }
                    if client_info.client_secret:
                        admin_credentials["client_secret"] = mask_string(
                            client_info.client_secret
                        )
                else:
                    admin_credentials = {}
                    logger.warning(
                        "No admin client info found for server %s", db_server.name
                    )
    else:  # currently: per user auth using api key OR oauth
        user_config = get_user_connection_config(db_server.id, email, db)
        user_authenticated = user_config is not None

        if user_authenticated and user_config:
            # Avoid hitting the MCP server when assembling response data.
            if (
                include_auth_config
                and db_server.auth_type != MCPAuthenticationType.OAUTH
            ):
                user_config_dict = extract_connection_data(user_config, apply_mask=True)
                user_credentials = user_config_dict.get(HEADER_SUBSTITUTIONS, {})

        if (
            db_server.auth_type == MCPAuthenticationType.OAUTH
            and db_server.admin_connection_config
        ):
            client_info = None
            oauth_admin_config_dict = extract_connection_data(
                db_server.admin_connection_config, apply_mask=False
            )
            client_info_raw = oauth_admin_config_dict.get(
                MCPOAuthKeys.CLIENT_INFO.value
            )
            params_raw = oauth_admin_config_dict.get(
                MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value
            )
            if isinstance(params_raw, dict):
                oauth_authorization_url_params = {
                    str(key): str(value) for key, value in params_raw.items()
                }
            if client_info_raw:
                client_info = OAuthClientInformationFull.model_validate(client_info_raw)
            if client_info:
                if not client_info.client_id:
                    raise ValueError("Stored client info had empty client ID")
                if can_view_admin_credentials:
                    admin_credentials = {
                        "client_id": mask_string(client_info.client_id),
                    }
                    if client_info.client_secret:
                        admin_credentials["client_secret"] = mask_string(
                            client_info.client_secret
                        )
            elif can_view_admin_credentials:
                admin_credentials = {}
                logger.warning("No client info found for server %s", db_server.name)

    # The header template is only meaningful for per-user API_TOKEN
    # servers, where it surfaces placeholder strings (e.g.
    # `Bearer {API_KEY}`) for the user-side credential prompt. OAuth
    # per-user servers do not get an `auth_template`: OAuth uses the
    # handshake URL (`/oauth/connect`) rather than a header template,
    # so the frontend never consumes one for OAuth flows.
    auth_template = None
    if (
        auth_performer == MCPAuthenticationPerformer.PER_USER
        and db_server.auth_type != MCPAuthenticationType.OAUTH
    ):
        try:
            template_config = db_server.admin_connection_config
            if template_config:
                template_config_dict = extract_connection_data(
                    template_config, apply_mask=False
                )
                headers = template_config_dict.get("headers", {})
                # Prefer the explicitly persisted list; fall back to deriving
                # from header placeholders for servers created before
                # `required_fields` was persisted.
                required_fields = template_config_dict.get(
                    "required_fields"
                ) or MCPAuthTemplate.derive_required_fields(headers)
                auth_template = MCPAuthTemplate(
                    headers=headers,
                    required_fields=required_fields,
                )
        except Exception as e:
            logger.warning(
                "Failed to parse auth template for server %s: %s", db_server.name, e
            )

    is_authenticated: bool = (
        db_server.auth_type == MCPAuthenticationType.NONE.value
        # Pass-through OAuth: user is authenticated via their login OAuth token
        or db_server.auth_type == MCPAuthenticationType.PT_OAUTH
        or (
            auth_performer == MCPAuthenticationPerformer.ADMIN
            and db_server.auth_type != MCPAuthenticationType.OAUTH
            and db_server.admin_connection_config_id is not None
        )
        or (
            auth_performer == MCPAuthenticationPerformer.PER_USER and user_authenticated
        )
    )

    # Calculate tool count from the relationship
    tool_count = len(db_server.current_actions) if db_server.current_actions else 0

    return MCPServer(
        id=db_server.id,
        name=db_server.name,
        description=db_server.description,
        server_url=db_server.server_url,
        owner=db_server.owner,
        transport=db_server.transport,
        auth_type=db_server.auth_type,
        auth_performer=auth_performer,
        is_authenticated=is_authenticated,
        user_authenticated=user_authenticated,
        status=db_server.status,
        last_refreshed_at=db_server.last_refreshed_at,
        tool_count=tool_count,
        auth_template=auth_template,
        user_credentials=user_credentials,
        admin_credentials=admin_credentials,
        oauth_authorization_url_params=oauth_authorization_url_params,
    )


@router.get("/servers/persona/{assistant_id}", response_model=MCPServersResponse)
def get_mcp_servers_for_assistant(
    assistant_id: str,
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPServersResponse:
    """Get MCP servers for an assistant"""

    logger.info("Fetching MCP servers for assistant: %s", assistant_id)

    try:
        persona_id = int(assistant_id)
        db_mcp_servers = get_mcp_servers_for_persona(persona_id, db, user)

        # Convert to API model format with opportunistic token refresh for OAuth
        mcp_servers = [
            _db_mcp_server_to_api_mcp_server(db_server, db, request_user=user)
            for db_server in db_mcp_servers
        ]

        return MCPServersResponse(assistant_id=assistant_id, mcp_servers=mcp_servers)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid assistant ID")
    except Exception as e:
        logger.error("Failed to fetch MCP servers: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


@router.get("/servers", response_model=MCPServersResponse)
def get_mcp_servers_for_user(
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPServersResponse:
    """List all MCP servers for use in agent configuration and chat UI.

    This endpoint is intentionally available to all authenticated users so they
    can attach MCP actions to assistants. Sensitive admin credentials are never
    returned.
    """
    db_mcp_servers = get_all_mcp_servers(db)
    mcp_servers = [
        _db_mcp_server_to_api_mcp_server(db_server, db, request_user=user)
        for db_server in db_mcp_servers
    ]
    return MCPServersResponse(mcp_servers=mcp_servers)


def _get_connection_config(
    mcp_server: DbMCPServer,
    is_admin: bool,  # noqa: ARG001
    user: User,
    db_session: Session,
) -> MCPConnectionConfig | None:
    """
    Get the connection config for an MCP server.
    is_admin is true when we want the config used for the admin panel

    """
    if mcp_server.auth_type == MCPAuthenticationType.NONE:
        return None

    # Pass-through OAuth uses the user's login OAuth token, not a stored config
    if mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
        return None

    if (
        mcp_server.auth_type == MCPAuthenticationType.API_TOKEN
        and mcp_server.auth_performer == MCPAuthenticationPerformer.ADMIN
    ):
        connection_config = mcp_server.admin_connection_config
    else:
        connection_config = get_user_connection_config(
            server_id=mcp_server.id, user_email=user.email, db_session=db_session
        )

    if not connection_config:
        raise HTTPException(
            status_code=401,
            detail="Authentication required for this MCP server",
        )

    return connection_config


@admin_router.get("/server/{server_id}/tools")
def admin_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, True, user)


class ToolSnapshotSource(str, Enum):
    DB = "db"
    MCP = "mcp"


@admin_router.get("/server/{server_id}/tools/snapshots")
def get_mcp_server_tools_snapshots(
    server_id: int,
    source: ToolSnapshotSource = ToolSnapshotSource.DB,
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> list[ToolSnapshot]:
    """
    Get tools for an MCP server as ToolSnapshot objects.

    Query Parameters:
    - source: "db" (default) - fetch from database only, "mcp" - discover from MCP server and sync to DB

    Returns: List of ToolSnapshot objects
    """
    from onyx.db.tools import get_tools_by_mcp_server_id

    try:
        # Verify the server exists
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    if source == ToolSnapshotSource.MCP:
        try:
            # Discover tools from MCP server and sync to DB
            _list_mcp_tools_by_id(server_id, db, True, user)

            # Successfully discovered tools, update status to CONNECTED
            update_mcp_server__no_commit(
                server_id=server_id,
                db_session=db,
                status=MCPServerStatus.CONNECTED,
                last_refreshed_at=datetime.datetime.now(datetime.timezone.utc),
            )
            db.commit()
        except Exception as e:
            update_mcp_server__no_commit(
                server_id=server_id,
                db_session=db,
                status=MCPServerStatus.AWAITING_AUTH,
            )
            db.commit()

            if isinstance(e, HTTPException):
                # Re-raise HTTP exceptions (e.g. 401, 400) so they are returned to client
                raise e

            logger.error("Failed to discover tools for MCP server: %s", e)
            raise HTTPException(status_code=500, detail="Failed to discover tools")

    # Fetch and return tools from database
    mcp_tools = get_tools_by_mcp_server_id(server_id, db, order_by_id=True)
    return [ToolSnapshot.from_model(tool) for tool in mcp_tools]


@router.get("/server/{server_id}/tools")
def user_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, False, user)


def _upsert_db_tools(
    discovered_tools: list[MCPLibTool],
    existing_by_name: dict[str, Tool],
    processed_names: set[str],
    mcp_server_id: int,
    db: Session,
) -> bool:
    db_dirty = False

    for tool in discovered_tools:
        tool_name = tool.name
        if not tool_name:
            continue

        processed_names.add(tool_name)
        description = tool.description or ""
        annotations_title = tool.annotations.title if tool.annotations else None
        display_name = tool.title or annotations_title or tool_name
        input_schema = tool.inputSchema

        if existing_tool := existing_by_name.get(tool_name):
            if existing_tool.description != description:
                existing_tool.description = description
                db_dirty = True
            if existing_tool.display_name != display_name:
                existing_tool.display_name = display_name
                db_dirty = True
            if existing_tool.mcp_input_schema != input_schema:
                existing_tool.mcp_input_schema = input_schema
                db_dirty = True
            continue

        new_tool = create_tool__no_commit(
            name=tool_name,
            description=description,
            openapi_schema=None,
            custom_headers=None,
            user_id=None,
            db_session=db,
            passthrough_auth=False,
            mcp_server_id=mcp_server_id,
            enabled=True,
        )
        new_tool.display_name = display_name
        new_tool.mcp_input_schema = input_schema
        db_dirty = True
    return db_dirty


def _list_mcp_tools_by_id(
    server_id: int,
    db: Session,
    is_admin: bool,
    user: User,
) -> MCPToolListResponse:
    """List available tools from an existing MCP server"""
    logger.info("Listing tools for MCP server: %s", server_id)

    try:
        # Get the MCP server
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if is_admin:
        _ensure_mcp_server_owner_or_admin(mcp_server, user)

    # Get connection config based on auth type
    # TODO: for now, only the admin that set up a per-user api key server can
    # see their configuration. This is probably not ideal. Other admins
    # can of course put their own credentials in and list the tools.
    connection_config = _get_connection_config(mcp_server, is_admin, user, db)

    # Allow access for NONE and PT_OAUTH (which use user's login token at runtime)
    if not connection_config and mcp_server.auth_type not in (
        MCPAuthenticationType.NONE,
        MCPAuthenticationType.PT_OAUTH,
    ):
        raise HTTPException(
            status_code=401,
            detail="This MCP server is not configured yet",
        )

    user_id = str(user.id)
    # Discover tools from the MCP server
    auth = None
    headers: dict[str, str] = {}

    if mcp_server.auth_type == MCPAuthenticationType.OAUTH:
        # TODO: just pass this in, but should work when auth is set already
        assert connection_config  # for mypy
        auth = make_oauth_provider(
            mcp_server,
            user_id,
            UNUSED_RETURN_PATH,
            connection_config.id,
            None,
        )
    elif mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
        # Pass-through OAuth: use the user's login OAuth token
        if user.oauth_accounts:
            user_oauth_token = user.oauth_accounts[0].access_token
            headers["Authorization"] = f"Bearer {user_oauth_token}"
        else:
            raise HTTPException(
                status_code=401,
                detail="Pass-through OAuth requires a user logged in with OAuth",
            )

    if connection_config:
        connection_config_dict = extract_connection_data(
            connection_config, apply_mask=False
        )
        headers.update(connection_config_dict.get("headers", {}))

    import time

    t1 = time.time()
    logger.info("Discovering tools for MCP server: %s: %s", mcp_server.name, t1)
    server_url = mcp_server.server_url

    if mcp_server.transport is None:
        raise HTTPException(
            status_code=400,
            detail="MCP server transport is not configured",
        )

    discovered_tools = discover_mcp_tools(
        server_url,
        headers,
        transport=mcp_server.transport,
        auth=auth,
    )
    logger.info(
        "Discovered %s tools for MCP server: %s: %s",
        len(discovered_tools),
        mcp_server.name,
        time.time() - t1,
    )
    update_mcp_server__no_commit(
        server_id=server_id,
        db_session=db,
        status=MCPServerStatus.CONNECTED,
    )
    db.commit()

    if is_admin:
        existing_tools = get_tools_by_mcp_server_id(mcp_server.id, db)
        existing_by_name = {db_tool.name: db_tool for db_tool in existing_tools}
        processed_names: set[str] = set()

        db_dirty = _upsert_db_tools(
            discovered_tools, existing_by_name, processed_names, mcp_server.id, db
        )

        for name, db_tool in existing_by_name.items():
            if name not in processed_names:
                delete_tool__no_commit(db_tool.id, db)
                db_dirty = True

        if db_dirty:
            db.commit()

    # Truncate tool descriptions to prevent overly long responses
    for tool in discovered_tools:
        if tool.description:
            tool.description = _truncate_description(tool.description)

    # TODO: Also list resources from the MCP server
    # resources = discover_mcp_resources(mcp_server, connection_config)

    return MCPToolListResponse(
        server_id=server_id,
        server_name=mcp_server.name,
        server_url=mcp_server.server_url,
        tools=discovered_tools,
    )


def _upsert_mcp_server(
    request: MCPToolCreateRequest,
    db_session: Session,
    user: User,
) -> DbMCPServer:
    """
    Creates a new or edits an existing MCP server. Returns the DB model
    """
    mcp_server = None
    admin_config = None

    changing_connection_config = True

    # Handle existing server update
    if request.existing_server_id:
        try:
            mcp_server = get_mcp_server_by_id(request.existing_server_id, db_session)
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail=f"MCP server with ID {request.existing_server_id} not found",
            )
        _ensure_mcp_server_owner_or_admin(mcp_server, user)
        client_info: OAuthClientInformationFull | None = None
        existing_admin_config_dict: MCPConnectionData = MCPConnectionData(headers={})
        if mcp_server.admin_connection_config:
            existing_admin_config_dict = extract_connection_data(
                mcp_server.admin_connection_config, apply_mask=False
            )
            client_info_raw = existing_admin_config_dict.get(
                MCPOAuthKeys.CLIENT_INFO.value
            )
            if client_info_raw:
                client_info = OAuthClientInformationFull.model_validate(client_info_raw)

        # Resolve the effective OAuth credentials, falling back to the stored
        # values for any field the frontend marked as unchanged. This protects
        # the change-detection comparison below from spurious diffs caused by
        # masked placeholders being replayed.
        if client_info and request.auth_type == MCPAuthenticationType.OAUTH:
            (
                request.oauth_client_id,
                request.oauth_client_secret,
            ) = _resolve_oauth_credentials(
                request_client_id=request.oauth_client_id,
                request_client_id_changed=request.oauth_client_id_changed,
                request_client_secret=request.oauth_client_secret,
                request_client_secret_changed=request.oauth_client_secret_changed,
                existing_client=client_info,
            )

        # Same pattern for per-user API_TOKEN: resolve admin credentials
        # against the admin's stored per-user row
        existing_admin_per_user_creds: dict[str, str] = {}
        existing_template_headers: dict[str, str] = {}
        if mcp_server.admin_connection_config:
            existing_template_headers = (
                existing_admin_config_dict.get("headers", {}) or {}
            )
        if (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.PER_USER
            and user.email
        ):
            existing_admin_per_user_config = get_user_connection_config(
                mcp_server.id, user.email, db_session
            )
            if existing_admin_per_user_config:
                existing_admin_per_user_dict = extract_connection_data(
                    existing_admin_per_user_config, apply_mask=False
                )
                existing_admin_per_user_creds = (
                    existing_admin_per_user_dict.get(HEADER_SUBSTITUTIONS) or {}
                )
            if request.admin_credentials is not None:
                request.admin_credentials = _resolve_admin_credentials(
                    request_credentials=request.admin_credentials,
                    request_credentials_changed=request.admin_credentials_changed,
                    existing_user_credentials=existing_admin_per_user_creds,
                )

        api_token_creds_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.PER_USER
            and existing_admin_per_user_creds != (request.admin_credentials or {})
        )
        api_token_template_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and request.auth_performer == MCPAuthenticationPerformer.PER_USER
            and request.auth_template is not None
            and request.auth_template.headers != existing_template_headers
        )
        api_token_scheme_changed = (
            request.auth_type == MCPAuthenticationType.API_TOKEN
            and (
                request.auth_type != mcp_server.auth_type
                or request.auth_performer != mcp_server.auth_performer
            )
        )

        changing_connection_config = (
            not mcp_server.admin_connection_config
            or (
                request.auth_type == MCPAuthenticationType.OAUTH
                and (
                    client_info is None
                    or request.oauth_client_id != client_info.client_id
                    or request.oauth_client_secret != (client_info.client_secret or "")
                    or _oauth_authorization_url_params_changed(
                        existing_admin_config_dict,
                        request.oauth_authorization_url_params,
                    )
                )
            )
            or (
                request.auth_type == MCPAuthenticationType.API_TOKEN
                and (
                    api_token_creds_changed
                    or api_token_template_changed
                    or api_token_scheme_changed
                )
            )
            or (request.transport != mcp_server.transport)
        )

        # OAuth: wipe every user's tokens — re-handshake required.
        # API_TOKEN: drop only the shared template; the admin's per-user
        # row is upserted in place below.
        if (
            changing_connection_config
            and mcp_server.admin_connection_config_id
            and request.auth_type == MCPAuthenticationType.OAUTH
        ):
            delete_all_user_connection_configs_for_server_no_commit(
                mcp_server.id, db_session
            )
        elif (
            changing_connection_config
            and mcp_server.admin_connection_config_id
            and request.auth_type == MCPAuthenticationType.API_TOKEN
        ):
            delete_connection_config(mcp_server.admin_connection_config_id, db_session)

        # Update the server with new values
        mcp_server = update_mcp_server__no_commit(
            server_id=request.existing_server_id,
            db_session=db_session,
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
            auth_performer=request.auth_performer,
            transport=request.transport,
        )

        logger.info(
            "Updated existing MCP server '%s' with ID %s", request.name, mcp_server.id
        )

    else:
        # Handle new server creation
        # Prevent duplicate server creation with same URL
        normalized_url = (request.server_url or "").strip()
        if not normalized_url:
            raise HTTPException(status_code=400, detail="server_url is required")

        if not user.email:
            raise HTTPException(
                status_code=400,
                detail="Authenticated user email required to create MCP servers",
            )

        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
            auth_performer=request.auth_performer,
            transport=request.transport or MCPTransport.STREAMABLE_HTTP,
            db_session=db_session,
        )

        logger.info(
            "Created new MCP server '%s' with ID %s", request.name, mcp_server.id
        )

    # PT_OAUTH doesn't need stored connection config (uses user's login token)
    if (
        not changing_connection_config
        or request.auth_type == MCPAuthenticationType.NONE
        or request.auth_type == MCPAuthenticationType.PT_OAUTH
    ):
        return mcp_server

    # Create connection configs
    admin_connection_config_id = None
    if request.auth_performer == MCPAuthenticationPerformer.ADMIN and request.api_token:
        # Admin-managed server: create admin config with API token
        admin_config = create_connection_config(
            config_data=MCPConnectionData(
                headers={"Authorization": f"Bearer {request.api_token}"},
            ),
            mcp_server_id=mcp_server.id,
            db_session=db_session,
        )
        admin_connection_config_id = admin_config.id

    elif request.auth_performer == MCPAuthenticationPerformer.PER_USER:
        if request.auth_type == MCPAuthenticationType.API_TOKEN:
            # handled by model validation, this is just for mypy
            assert request.auth_template and request.admin_credentials

            # Per-user server: create template and save creator's per-user config
            template_data = request.auth_template

            # Trust the explicit list when present, otherwise derive it from
            # the header placeholders so the user-side modal always knows
            # which fields to prompt for. Older servers created before this
            # field was persisted are healed lazily on read.
            persisted_required_fields = (
                template_data.required_fields
                or MCPAuthTemplate.derive_required_fields(template_data.headers)
            )

            # Template config: placeholder headers + required fields only.
            # Admin's credentials live on the admin's own per-user row.
            template_config = create_connection_config(
                config_data=MCPConnectionData(
                    headers=template_data.headers,
                    required_fields=persisted_required_fields,
                ),
                mcp_server_id=mcp_server.id,
                user_email="",
                db_session=db_session,
            )

            # Seed (or refresh) the admin's own per-user row.
            upsert_user_connection_config(
                server_id=mcp_server.id,
                user_email=user.email,
                config_data=MCPConnectionData(
                    headers=_build_headers_from_template(
                        template_data, request.admin_credentials, user.email
                    ),
                    header_substitutions=request.admin_credentials,
                ),
                db_session=db_session,
            )
            admin_connection_config_id = template_config.id
        elif request.auth_type == MCPAuthenticationType.OAUTH:
            # Create initial admin config. If client credentials were provided,
            # seed client_info so the OAuth provider can skip dynamic
            # registration; otherwise, the provider will attempt it.
            # NOTE: must go through the shared helper so
            # `token_endpoint_auth_method` matches what `_connect_oauth`'s
            # update path expects to preserve later.
            cfg: MCPConnectionData = _build_oauth_admin_config_data(
                client_id=request.oauth_client_id,
                client_secret=request.oauth_client_secret,
                authorization_url_params=request.oauth_authorization_url_params,
            )

            admin_config = create_connection_config(
                config_data=cfg,
                mcp_server_id=mcp_server.id,
                user_email="",
                db_session=db_session,
            )
            admin_connection_config_id = admin_config.id

            # create user connection config
            create_connection_config(
                config_data=cfg,
                mcp_server_id=mcp_server.id,
                user_email=user.email,
                db_session=db_session,
            )
    elif request.auth_performer == MCPAuthenticationPerformer.ADMIN:
        raise HTTPException(
            status_code=400,
            detail="Admin authentication is not yet supported for MCP servers: user per-user",
        )

    # Update server with config IDs
    if admin_connection_config_id is not None:
        mcp_server = update_mcp_server__no_commit(
            server_id=mcp_server.id,
            db_session=db_session,
            admin_connection_config_id=admin_connection_config_id,
        )

    db_session.commit()
    return mcp_server


def _sync_tools_for_server(
    mcp_server: DbMCPServer,
    selected_tools: set[str],
    db_session: Session,
) -> int:
    """Toggle enabled state for MCP tools that exist for the server.
    Updates to the db model of a tool all happen when the user Lists Tools.
    This ensures that the the tools added to the db match what the user sees in the UI,
    even if the underlying tool has changed on the server after list tools is called.
    That's a corner case anyways; the admin should go back and update the server by re-listing tools.
    """

    updated_tools = 0

    existing_tools = get_tools_by_mcp_server_id(mcp_server.id, db_session)
    existing_by_name = {tool.name: tool for tool in existing_tools}

    # Disable any existing tools that were not processed above
    for tool_name, db_tool in existing_by_name.items():
        should_enable = tool_name in selected_tools
        if db_tool.enabled != should_enable:
            db_tool.enabled = should_enable
            updated_tools += 1

    return updated_tools


@admin_router.get("/servers/{server_id}", response_model=MCPServer)
def get_mcp_server_detail(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPServer:
    """Return details for one MCP server if user has access"""
    try:
        server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(server, user)

    # TODO: user permissions per mcp server not yet implemented, for now
    # permissions are based on access to assistants
    # # Quick permission check – admin or user has access
    # if user and server not in user.accessible_mcp_servers and not user.is_superuser:
    #     raise HTTPException(status_code=403, detail="Forbidden")

    return _db_mcp_server_to_api_mcp_server(
        server,
        db_session,
        include_auth_config=True,
        request_user=user,
    )


@admin_router.get("/tools")
def get_all_mcp_tools(
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),  # noqa: ARG001
) -> list:
    """Get all tools associated with MCP servers, including both enabled and disabled tools"""
    from sqlalchemy import select

    from onyx.db.models import Tool

    # Query MCP tools ordered by ID to maintain consistent ordering
    stmt = select(Tool).where(Tool.mcp_server_id.is_not(None)).order_by(Tool.id)

    mcp_tools = db.scalars(stmt).all()

    # Convert to ToolSnapshot format
    return [ToolSnapshot.from_model(tool) for tool in mcp_tools]


@admin_router.patch("/server/{server_id}/status")
def update_mcp_server_status(
    server_id: int,
    status: MCPServerStatus,
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> dict[str, str]:
    """Update the status of an MCP server"""
    logger.info("Updating MCP server %s status to %s", server_id, status)

    try:
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    update_mcp_server__no_commit(
        server_id=server_id,
        db_session=db,
        status=status,
    )
    db.commit()

    logger.info("Successfully updated MCP server %s status to %s", server_id, status)
    return {"message": f"Server status updated to {status.value}"}


@admin_router.get("/servers", response_model=MCPServersResponse)
def get_mcp_servers_for_admin(
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPServersResponse:
    """Get all MCP servers for admin display"""

    logger.info("Fetching all MCP servers for admin display")

    try:
        db_mcp_servers = get_all_mcp_servers(db)

        # Convert to API model format
        mcp_servers = [
            _db_mcp_server_to_api_mcp_server(db_server, db, request_user=user)
            for db_server in db_mcp_servers
        ]

        return MCPServersResponse(mcp_servers=mcp_servers)

    except Exception as e:
        logger.error("Failed to fetch MCP servers for admin: %s:%s", type(e), e)
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


@admin_router.get("/server/{server_id}/db-tools")
def get_mcp_server_db_tools(
    server_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> ServerToolsResponse:
    """Get existing database tools created for an MCP server"""
    logger.info("Getting database tools for MCP server: %s", server_id)

    try:
        # Verify the server exists
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    # Get all tools associated with this MCP server
    mcp_tools = get_tools_by_mcp_server_id(server_id, db)

    # Convert to response format
    tools_data = []
    for tool in mcp_tools:
        # Extract the tool name from the full name (remove server prefix)
        tool_name = tool.name
        if tool.mcp_server and tool_name.startswith(f"{tool.mcp_server.name}_"):
            tool_name = tool_name[len(f"{tool.mcp_server.name}_") :]

        tools_data.append(
            MCPToolDescription(
                id=tool.id,
                name=tool_name,
                display_name=tool.display_name or tool_name,
                description=_truncate_description(tool.description),
            )
        )

    return ServerToolsResponse(
        server_id=server_id,
        server_name=mcp_server.name,
        server_url=mcp_server.server_url,
        tools=tools_data,
    )


@admin_router.post("/servers/create", response_model=MCPServerCreateResponse)
def upsert_mcp_server(
    request: MCPToolCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPServerCreateResponse:
    """Create or update an MCP server (no tools yet)"""

    # Validate auth_performer for non-none auth types
    if request.auth_type != MCPAuthenticationType.NONE and not request.auth_performer:
        raise HTTPException(
            status_code=400, detail="auth_performer is required for non-none auth types"
        )

    try:
        mcp_server = _upsert_mcp_server(request, db_session, user)

        if (
            request.auth_type
            not in (MCPAuthenticationType.NONE, MCPAuthenticationType.PT_OAUTH)
            and mcp_server.admin_connection_config_id is None
        ):
            raise HTTPException(
                status_code=500, detail="Failed to set admin connection config"
            )
        db_session.commit()

        action_verb = "Updated" if request.existing_server_id else "Created"
        logger.info(
            "%s MCP server '%s' with ID %s", action_verb, request.name, mcp_server.id
        )

        if mcp_server.auth_type is None:
            raise HTTPException(
                status_code=500, detail="MCP server auth_type not configured"
            )
        auth_type_str = mcp_server.auth_type.value

        return MCPServerCreateResponse(
            server_id=mcp_server.id,
            server_name=mcp_server.name,
            server_url=mcp_server.server_url,
            auth_type=auth_type_str,
            auth_performer=(
                request.auth_performer.value if request.auth_performer else None
            ),
            is_authenticated=(
                mcp_server.auth_type == MCPAuthenticationType.NONE.value
                or request.auth_performer == MCPAuthenticationPerformer.ADMIN
            ),
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.exception("Failed to create/update MCP tool")
        raise HTTPException(
            status_code=500, detail=f"Failed to create/update MCP tool: {str(e)}"
        )


@admin_router.post("/servers/update", response_model=MCPServerUpdateResponse)
def update_mcp_server_with_tools(
    request: MCPToolUpdateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPServerUpdateResponse:
    """Update an MCP server and associated tools"""

    try:
        mcp_server = get_mcp_server_by_id(request.server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    if mcp_server.admin_connection_config_id is None and mcp_server.auth_type not in (
        MCPAuthenticationType.NONE,
        MCPAuthenticationType.PT_OAUTH,
    ):
        raise HTTPException(
            status_code=400, detail="MCP server has no admin connection config"
        )

    name_changed = request.name is not None and request.name != mcp_server.name
    description_changed = (
        request.description is not None
        and request.description != mcp_server.description
    )
    if name_changed or description_changed:
        mcp_server = update_mcp_server__no_commit(
            server_id=mcp_server.id,
            db_session=db_session,
            name=request.name if name_changed else None,
            description=request.description if description_changed else None,
        )

    selected_names = set(request.selected_tools or [])
    updated_tools = _sync_tools_for_server(
        mcp_server,
        selected_names,
        db_session,
    )

    db_session.commit()

    return MCPServerUpdateResponse(
        server_id=mcp_server.id,
        server_name=mcp_server.name,
        updated_tools=updated_tools,
    )


@admin_router.post("/server", response_model=MCPServer)
def create_mcp_server_simple(
    request: MCPServerSimpleCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPServer:
    """Create MCP server with minimal information - auth to be configured later"""

    mcp_server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=request.name,
        description=request.description,
        server_url=request.server_url,
        auth_type=None,  # To be configured later
        transport=None,  # To be configured later
        auth_performer=None,  # To be configured later
        db_session=db_session,
    )

    db_session.commit()

    return MCPServer(
        id=mcp_server.id,
        name=mcp_server.name,
        description=mcp_server.description,
        server_url=mcp_server.server_url,
        owner=mcp_server.owner,
        transport=mcp_server.transport,
        auth_type=mcp_server.auth_type,
        auth_performer=mcp_server.auth_performer,
        is_authenticated=False,  # Not authenticated yet
        status=mcp_server.status,
        tool_count=0,  # New server, no tools yet
        auth_template=None,
        user_credentials=None,
        admin_credentials=None,
    )


@admin_router.patch("/server/{server_id}", response_model=MCPServer)
def update_mcp_server_simple(
    server_id: int,
    request: MCPServerSimpleUpdateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> MCPServer:
    """Update MCP server basic information (name, description, URL)"""
    try:
        mcp_server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    # Update only provided fields
    updated_server = update_mcp_server__no_commit(
        server_id=server_id,
        db_session=db_session,
        name=request.name,
        description=request.description,
        server_url=request.server_url,
    )

    db_session.commit()

    # Return the updated server in API format
    return _db_mcp_server_to_api_mcp_server(
        updated_server, db_session, request_user=user
    )


@admin_router.delete("/server/{server_id}")
def delete_mcp_server_admin(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_curator_or_admin_user),
) -> dict:
    """Delete an MCP server and cascading related objects (tools, configs)."""
    try:
        # Ensure it exists
        server = get_mcp_server_by_id(server_id, db_session)

        _ensure_mcp_server_owner_or_admin(server, user)

        # Log tools that will be deleted for debugging
        tools_to_delete = get_tools_by_mcp_server_id(server_id, db_session)
        logger.info(
            "Deleting MCP server %s (%s) with %s tools",
            server_id,
            server.name,
            len(tools_to_delete),
        )
        for tool in tools_to_delete:
            logger.debug("  - Tool to delete: %s (ID: %s)", tool.name, tool.id)

        # Cascade behavior handled by FK ondelete in DB
        delete_mcp_server(server_id, db_session)

        # Verify tools were deleted
        remaining_tools = get_tools_by_mcp_server_id(server_id, db_session)
        if remaining_tools:
            logger.error(
                "WARNING: %s tools still exist after deleting MCP server %s",
                len(remaining_tools),
                server_id,
            )
            # Manually delete them as a fallback
            for tool in remaining_tools:
                logger.info(
                    "Manually deleting orphaned tool: %s (ID: %s)", tool.name, tool.id
                )
                delete_tool__no_commit(tool.id, db_session)
        db_session.commit()

        return {"success": True}
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except Exception as e:
        logger.error("Failed to delete MCP server %s: %s", server_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete MCP server")
