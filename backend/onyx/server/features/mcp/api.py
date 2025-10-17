import asyncio
import base64
import hashlib
import json
from collections.abc import Awaitable
from secrets import token_urlsafe
from typing import cast
from typing import Literal
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.auth import OAuthToken
from mcp.types import InitializeResult
from mcp.types import Tool as MCPLibTool
from pydantic import AnyUrl
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.mcp import create_connection_config
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.mcp import delete_connection_config
from onyx.db.mcp import delete_mcp_server
from onyx.db.mcp import delete_user_connection_configs_for_server
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
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.mcp.models import MCPApiKeyResponse
from onyx.server.features.mcp.models import MCPAuthTemplate
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.server.features.mcp.models import MCPOAuthCallbackResponse
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.models import MCPServer
from onyx.server.features.mcp.models import MCPServerCreateResponse
from onyx.server.features.mcp.models import MCPServersResponse
from onyx.server.features.mcp.models import MCPServerUpdateResponse
from onyx.server.features.mcp.models import MCPToolCreateRequest
from onyx.server.features.mcp.models import MCPToolListResponse
from onyx.server.features.mcp.models import MCPToolUpdateRequest
from onyx.server.features.mcp.models import MCPUserCredentialsRequest
from onyx.server.features.mcp.models import MCPUserOAuthConnectRequest
from onyx.server.features.mcp.models import MCPUserOAuthConnectResponse
from onyx.tools.tool_implementations.mcp.mcp_client import discover_mcp_tools
from onyx.tools.tool_implementations.mcp.mcp_client import initialize_mcp_client
from onyx.tools.tool_implementations.mcp.mcp_client import log_exception_group
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _truncate_description(description: str | None, max_length: int = 500) -> str:
    """Truncate description to max_length characters, adding ellipsis if truncated."""
    if not description:
        return ""
    if len(description) <= max_length:
        return description
    return description[: max_length - 3] + "..."


router = APIRouter(prefix="/mcp")
admin_router = APIRouter(prefix="/admin/mcp")
STATE_TTL_SECONDS = 60 * 5  # 5 minutes
OAUTH_WAIT_SECONDS = 30  # Give the user 30 seconds to complete the OAuth flow
UNUSED_RETURN_PATH = "unused_path"

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


REQUESTED_SCOPE: str | None = None


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
            tokens_raw = config.config.get(MCPOAuthKeys.TOKENS.value)
            if tokens_raw:
                return OAuthToken.model_validate(tokens_raw)
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config.config[MCPOAuthKeys.TOKENS.value] = tokens.model_dump(mode="json")
            cfg_headers = {
                "Authorization": f"{tokens.token_type} {tokens.access_token}"
            }
            config.config["headers"] = cfg_headers
            update_connection_config(config.id, db_session, config.config)
            if self.alt_config_id:
                update_connection_config(self.alt_config_id, db_session, config.config)

                # signal the oauth callback that token exchange is complete
                r = get_redis_client()
                r.rpush(key_tokens(str(self.alt_config_id)), tokens.model_dump_json())
                r.expire(key_tokens(str(self.alt_config_id)), OAUTH_WAIT_SECONDS)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            client_info_raw = config.config.get(MCPOAuthKeys.CLIENT_INFO.value)
            if client_info_raw:
                return OAuthClientInformationFull.model_validate(client_info_raw)
            return None

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        with get_session_with_current_tenant() as db_session:
            config = self._ensure_connection_config(db_session)
            config.config[MCPOAuthKeys.CLIENT_INFO.value] = info.model_dump(mode="json")
            update_connection_config(config.id, db_session, config.config)
            if self.alt_config_id:
                update_connection_config(self.alt_config_id, db_session, config.config)


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
        r.rpush(key_auth_url(user_id), auth_url)
        r.expire(key_auth_url(user_id), OAUTH_WAIT_SECONDS)
        r.set(key_state(user_id), state_obj.model_dump_json(), ex=STATE_TTL_SECONDS)

        # Return immediately; the HTTP layer will read the stored URL and send it to the browser.

    async def callback_handler() -> tuple[str, str | None]:
        r = get_redis_client()
        # Wait up to TTL for the code published by the /oauth/callback route
        state = r.get(key_state(user_id))
        if isinstance(state, Awaitable):
            state = await state
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

        code_state_bytes = cast(tuple[bytes, bytes], pop)

        code_state_dict = json.loads(code_state_bytes[1].decode())

        code = code_state_dict["code"]

        if code_state_dict["state"] != state_obj.state:
            raise RuntimeError("Invalid state in OAuth callback")

        # Optional: cleanup
        r.delete(key_auth_url(user_id), key_state(user_id))
        return code, state_obj.state

    return OAuthClientProvider(
        server_url=mcp_server.server_url,
        client_metadata=OAuthClientMetadata(
            client_name=mcp_server.name,
            redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=REQUESTED_SCOPE,  # TODO: do we need to pass this in? maybe make configurable
        ),
        storage=OnyxTokenStorage(connection_config_id, admin_config_id),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


def _build_headers_from_template(
    template_data: MCPAuthTemplate, credentials: dict[str, str], user_email: str
) -> dict[str, str]:
    """Build headers dict from template and credentials"""
    headers = {}
    template_headers = template_data.headers

    for name, value_template in template_headers.items():
        # Replace placeholders
        value = value_template
        for key, cred_value in credentials.items():
            value = value.replace(f"{{{key}}}", cred_value)
        value = value.replace("{user_email}", user_email)

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
        logger.error(f"Failed to test MCP server credentials: {e}")
        return False, f"Connection failed: {str(e)}"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    verifier = b64url(token_urlsafe(64).encode())
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


async def discover_auth_server_url(
    oauth_auth: OAuthClientProvider, oauth_url: str, well_known_override: str
) -> str:
    """
    Only call this function when the client provider's context contains a non-None oauth_metadata
    """
    oauth_metadata_request = oauth_auth._create_oauth_metadata_request(
        well_known_override
    )
    import httpx

    async with httpx.AsyncClient() as client:
        oauth_metadata_response = await client.send(oauth_metadata_request)

    if oauth_metadata_response.status_code == 200:
        await oauth_auth._handle_oauth_metadata_response(oauth_metadata_response)
        assert oauth_auth.context.oauth_metadata  # guaranteed by caller
        # need to do this explicitly because we're overwriting the scope in the client metadata
        oauth_auth.context.client_metadata.scope = " ".join(
            oauth_auth.context.oauth_metadata.scopes_supported or []
        )
        prev_oauth_url_parts = urlsplit(oauth_url)
        # Construct new URL by adding query params from previous OAuth URL to the authorization endpoint
        # Update scope in the OAuth URL with the new client metadata scopes
        if oauth_auth.context.client_metadata.scope:
            prev_query_params = dict(parse_qsl(prev_oauth_url_parts.query))
            prev_query_params["scope"] = oauth_auth.context.client_metadata.scope
            prev_oauth_url_parts = prev_oauth_url_parts._replace(
                query=urlencode(prev_query_params)
            )
        parsed_auth_endpoint = urlsplit(
            str(oauth_auth.context.oauth_metadata.authorization_endpoint)
        )
        existing_query_params = dict(parse_qsl(parsed_auth_endpoint.query))
        prev_query_params = dict(parse_qsl(prev_oauth_url_parts.query))

        # Merge query parameters (previous params take precedence)
        merged_params = {**existing_query_params, **prev_query_params}

        # Reconstruct the URL with merged query parameters
        oauth_url = urlunsplit(
            parsed_auth_endpoint._replace(query=urlencode(merged_params))
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Failed to retrieve OAuth metadata: Code"
                f" {oauth_metadata_response.status_code} text: {oauth_metadata_response.text}"
            ),
        )
    return oauth_url


class MCPOauthState(BaseModel):
    server_id: int
    return_path: str
    is_admin: bool
    state: str


@admin_router.post("/oauth/connect", response_model=MCPUserOAuthConnectResponse)
async def connect_admin_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
) -> MCPUserOAuthConnectResponse:
    """Connect OAuth flow for admin MCP server authentication"""
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Must be logged in as a valid user to connect to MCP server via OAuth",
        )
    return await _connect_oauth(request, db, is_admin=True, user=user)


@router.post("/oauth/connect", response_model=MCPUserOAuthConnectResponse)
async def connect_user_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> MCPUserOAuthConnectResponse:
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Must be logged in as a valid user to connect to MCP server via OAuth",
        )
    return await _connect_oauth(request, db, is_admin=False, user=user)


async def _connect_oauth(
    request: MCPUserOAuthConnectRequest,
    db: Session,
    is_admin: bool,
    user: User,
) -> MCPUserOAuthConnectResponse:
    """Connect OAuth flow for per-user MCP server authentication"""

    logger.info(f"Initiating per-user OAuth for server: {request.server_id}")

    try:
        server_id = int(request.server_id)
        mcp_server = get_mcp_server_by_id(server_id, db)
    except Exception:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    if mcp_server.auth_type != MCPAuthenticationType.OAUTH:
        raise HTTPException(
            status_code=400,
            detail=f"Server was configured with authentication type {mcp_server.auth_type.value}",
        )

    # Create admin config with client info if provided
    config_data = MCPConnectionData(headers={})
    if request.oauth_client_id and request.oauth_client_secret:
        client_info = OAuthClientInformationFull(
            client_id=request.oauth_client_id,
            client_secret=request.oauth_client_secret,
            redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=REQUESTED_SCOPE,  # TODO: allow specifying scopes?
        )
        config_data[MCPOAuthKeys.CLIENT_INFO.value] = client_info.model_dump(
            mode="json"
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

    if connection_config is None:
        connection_config = create_connection_config(
            config_data=config_data,
            mcp_server_id=mcp_server.id,
            user_email=user.email,
            db_session=db,
        )
    else:
        update_connection_config(connection_config.id, db, config_data)

    db.commit()

    is_connected = (
        MCPOAuthKeys.CLIENT_INFO.value in connection_config.config
        and connection_config.config.get("headers")
    )
    # Step 1: make unauthenticated request and parse returned www authenticate header
    # Ensure we have a trailing slash for the MCP endpoint

    # always make a http request for the initial probe
    transport = mcp_server.transport if is_connected else MCPTransport.STREAMABLE_HTTP
    probe_url = mcp_server.server_url.rstrip("/") + "/"
    logger.info(f"Probing OAuth server at: {probe_url}")

    oauth_auth = make_oauth_provider(
        mcp_server,
        str(user.id),
        request.return_path,
        connection_config.id,
        mcp_server.admin_connection_config_id,
    )

    # start the oauth handshake in the background
    # the background task will block on the callback handler after setting
    # the auth_url for us to send to the frontend. The callback handler waits for
    # the auth code to be available in redis; this code gets set by our callback endpoint
    # which is called by the frontend after the user goes through the login flow.
    async def tmp_func() -> InitializeResult:
        try:
            x = await initialize_mcp_client(
                probe_url,
                connection_headers=connection_config.config.get("headers", {}),
                transport=transport,
                auth=oauth_auth,
            )
            logger.info(f"OAuth initialization completed successfully: {x}")
            return x
        except Exception:
            logger.exception("OAuth initialization failed")
            raise

    init_task = asyncio.create_task(tmp_func())

    # Wait for whichever happens first:
    # 1) The OAuth redirect URL becomes available in Redis (we should return it)
    # 2) The initialize task completes (tokens already valid) — return to the provided return_path
    r = get_redis_client()
    loop = asyncio.get_running_loop()

    async def wait_auth_url() -> str | None:
        raw = await loop.run_in_executor(
            None,
            lambda: r.blpop([key_auth_url(str(user.id))], timeout=OAUTH_WAIT_SECONDS),
        )
        if raw is None:
            return None
        tup = cast(tuple[bytes, bytes], raw)
        return tup[1].decode()

    auth_task = None if is_connected else asyncio.create_task(wait_auth_url())

    done, pending = await asyncio.wait(
        [init_task] + ([auth_task] if auth_task else []),
        return_when=asyncio.FIRST_COMPLETED,
    )

    # If we got an auth URL first, return it
    if auth_task in done:
        oauth_url = await auth_task
        # If no URL was retrieved within the timeout, treat as error
        if not oauth_url:
            # If initialization also finished, treat as already authenticated
            if init_task.done() and not init_task.cancelled():
                try:
                    init_result = init_task.result()
                    logger.info(
                        f"OAuth initialization completed during timeout: {init_result}"
                    )
                    return MCPUserOAuthConnectResponse(
                        server_id=int(request.server_id),
                        oauth_url=request.return_path,
                    )
                except Exception as e:
                    logger.error(f"OAuth initialization failed during timeout: {e}")
                    raise HTTPException(
                        status_code=400, detail=f"OAuth initialization failed: {str(e)}"
                    )
            raise HTTPException(status_code=400, detail="Auth URL retrieval timed out")

        # TODO: this is a hack that lets us work around the broken discovery mechanisms
        # in the mcp client library when using Okta as Idp. Okta's discovery urls
        # put the well-known section at the end, and before the mcp client library
        # tries that variant it tries to use just the base path + well known. this path
        # is valid for Okta (returns 200), giving the wrong metadata.

        if oauth_auth.context.auth_server_url and oauth_auth.context.oauth_metadata:

            parsed_url = urlsplit(oauth_auth.context.auth_server_url)

            query_params = dict(parse_qsl(parsed_url.query))
            well_known_override = query_params.get("well_known_override")
            # effectively copied from the mcp client library
            if well_known_override:
                oauth_url = await discover_auth_server_url(
                    oauth_auth, oauth_url, well_known_override
                )
                # TODO: at the moment we do not handle dynamic client registration in this flow.
                # It's meant as a hack to work with edge case Idps with discovery urls that disagree
                # with the ones the client library talks with.

        logger.info(
            f"Connected to auth url: {oauth_url} for mcp server: {mcp_server.name}"
        )
        return MCPUserOAuthConnectResponse(
            server_id=int(request.server_id), oauth_url=oauth_url
        )

    # Otherwise, initialization finished first — no redirect needed; go back to return_path
    for t in pending:
        t.cancel()
    try:
        init_result = init_task.result()
        logger.info(f"OAuth initialization completed without redirect: {init_result}")
    except Exception as e:
        if isinstance(e, ExceptionGroup):
            saved_e = log_exception_group(e)
        else:
            saved_e = e
        logger.error(f"OAuth initialization failed: {saved_e}")
        # If initialize failed and we also didn't get an auth URL, surface an error
        raise HTTPException(
            status_code=400, detail=f"Failed to initialize OAuth client: {str(saved_e)}"
        )

    return MCPUserOAuthConnectResponse(
        server_id=int(request.server_id),
        oauth_url=request.return_path,
    )


@router.post("/oauth/callback", response_model=MCPOAuthCallbackResponse)
async def process_oauth_callback(
    request: Request,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
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
    user_id = str(user.id) if user else ""
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

    user.email if user else ""
    user_id = str(user.id) if user else ""

    r = get_redis_client()

    # Unblock the callback_handler in the asyncio background task
    r.rpush(key_code(user_id, state), json.dumps({"code": code, "state": state}))
    r.expire(key_code(user_id, state), OAUTH_WAIT_SECONDS)

    admin_config = mcp_server.admin_connection_config
    if admin_config is None:
        raise HTTPException(
            status_code=400,
            detail="Server referenced by callback is not configured, try recreating",
        )

    # Run the blocking blpop operation in a thread pool to avoid blocking the event loop
    # Wait until set_tokens is called
    admin_config_id = admin_config.id
    loop = asyncio.get_running_loop()
    tokens_raw = await loop.run_in_executor(
        None,
        lambda: r.blpop([key_tokens(str(admin_config_id))], timeout=OAUTH_WAIT_SECONDS),
    )
    if tokens_raw is None:
        raise HTTPException(status_code=400, detail="No tokens found")
    tokens_bytes = cast(tuple[bytes, bytes], tokens_raw)
    tokens = OAuthToken.model_validate_json(tokens_bytes[1].decode())

    if not tokens.access_token:
        raise HTTPException(status_code=400, detail="No access_token in OAuth response")

    db_session.commit()

    logger.info(
        f"server_id={str(mcp_server.id)} "
        f"server_name={mcp_server.name} "
        f"return_path={state_data.return_path}"
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
    user: User | None = Depends(current_user),
) -> MCPApiKeyResponse:
    """Save user credentials for template-based MCP server authentication"""

    logger.info(f"Saving user credentials for server: {request.server_id}")

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

    email = user.email if user else ""

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
        # Use template to create the full connection config
        try:
            # TODO: fix and/or type correctly w/base model
            config_data = MCPConnectionData(
                headers=auth_template.config.get("headers", {}),
                header_substitutions=auth_template.config.get(HEADER_SUBSTITUTIONS, {}),
            )
            for oauth_field_key in MCPOAuthKeys:
                field_key: Literal["client_info", "tokens", "metadata"] = (
                    oauth_field_key.value
                )
                if field_val := auth_template.config.get(field_key):
                    config_data[field_key] = field_val

        except Exception as e:
            logger.error(f"Failed to process authentication template: {e}")
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
            assert mcp_server.admin_connection_config_id is not None
            auth = make_oauth_provider(
                mcp_server,
                email,
                UNUSED_RETURN_PATH,
                mcp_server.admin_connection_config_id,
                None,
            )

        if HEADER_SUBSTITUTIONS in config_data:
            for key, value in config_data[HEADER_SUBSTITUTIONS].items():
                for k, v in config_data["headers"].items():
                    config_data["headers"][k] = v.replace(f"{{{key}}}", value)

        # Normalize URL to include trailing slash to avoid redirect/slow path handling
        server_url = mcp_server.server_url.rstrip("/") + "/"
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
            f"Could not validate credentials for server {mcp_server.name}: {e}"
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
            f"User credentials saved for server {mcp_server.name} and user {email}"
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
        logger.error(f"Failed to save user credentials: {e}")
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


def _ensure_mcp_server_owner_or_admin(server: DbMCPServer, user: User | None) -> None:
    if not user or user.role == UserRole.ADMIN:
        return

    user_email = user.email if user else None
    if not user_email or server.owner != user_email:
        raise HTTPException(
            status_code=403,
            detail="Curators can only modify MCP servers that they have created.",
        )


def _db_mcp_server_to_api_mcp_server(
    db_server: DbMCPServer, email: str, db: Session, include_auth_config: bool = False
) -> MCPServer:
    """Convert database MCP server to API model"""

    # Check if user has authentication configured and extract credentials
    auth_performer = db_server.auth_performer
    user_authenticated: bool | None = None
    user_credentials = None
    admin_credentials = None
    if db_server.auth_type == MCPAuthenticationType.NONE:
        user_authenticated = True  # No auth required
    elif auth_performer == MCPAuthenticationPerformer.ADMIN:
        user_authenticated = db_server.admin_connection_config is not None
        if include_auth_config and db_server.admin_connection_config is not None:
            if db_server.auth_type == MCPAuthenticationType.API_TOKEN:
                admin_credentials = {
                    "api_key": db_server.admin_connection_config.config["headers"][
                        "Authorization"
                    ].split(" ")[-1]
                }
            elif db_server.auth_type == MCPAuthenticationType.OAUTH:
                user_authenticated = False
                client_info = None
                client_info_raw = db_server.admin_connection_config.config.get(
                    MCPOAuthKeys.CLIENT_INFO.value
                )
                if client_info_raw:
                    client_info = OAuthClientInformationFull.model_validate(
                        client_info_raw
                    )
                if client_info:
                    admin_credentials = {
                        "client_id": client_info.client_id,
                        "client_secret": client_info.client_secret or "",
                    }
                else:
                    admin_credentials = {}
                    logger.warning(
                        f"No admin client info found for server {db_server.name}"
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
                user_credentials = user_config.config.get(HEADER_SUBSTITUTIONS, {})

        if (
            db_server.auth_type == MCPAuthenticationType.OAUTH
            and db_server.admin_connection_config
        ):
            client_info = None
            client_info_raw = db_server.admin_connection_config.config.get(
                MCPOAuthKeys.CLIENT_INFO.value
            )
            if client_info_raw:
                client_info = OAuthClientInformationFull.model_validate(client_info_raw)
            if client_info:
                admin_credentials = {
                    "client_id": client_info.client_id,
                    "client_secret": client_info.client_secret or "",
                }
            else:
                admin_credentials = {}
                logger.warning(f"No client info found for server {db_server.name}")

    # Get auth template if this is a per-user auth server
    auth_template = None
    if auth_performer == MCPAuthenticationPerformer.PER_USER:
        try:
            template_config = db_server.admin_connection_config
            if template_config:
                headers = template_config.config.get("headers", {})
                auth_template = MCPAuthTemplate(
                    headers=headers,
                    required_fields=[],  # would need to regex, not worth it
                )
        except Exception as e:
            logger.warning(
                f"Failed to parse auth template for server {db_server.name}: {e}"
            )

    is_authenticated: bool = (
        db_server.auth_type == MCPAuthenticationType.NONE.value
        or (
            auth_performer == MCPAuthenticationPerformer.ADMIN
            and db_server.auth_type != MCPAuthenticationType.OAUTH
            and db_server.admin_connection_config_id is not None
        )
        or (
            auth_performer == MCPAuthenticationPerformer.PER_USER and user_authenticated
        )
    )

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
        auth_template=auth_template,
        user_credentials=user_credentials,
        admin_credentials=admin_credentials,
    )


@router.get("/servers/persona/{assistant_id}", response_model=MCPServersResponse)
def get_mcp_servers_for_assistant(
    assistant_id: str,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> MCPServersResponse:
    """Get MCP servers for an assistant"""

    logger.info(f"Fetching MCP servers for assistant: {assistant_id}")

    email = user.email if user else ""
    try:
        persona_id = int(assistant_id)
        db_mcp_servers = get_mcp_servers_for_persona(persona_id, db, user)

        # Convert to API model format with opportunistic token refresh for OAuth
        mcp_servers = [
            _db_mcp_server_to_api_mcp_server(db_server, email, db)
            for db_server in db_mcp_servers
        ]

        return MCPServersResponse(assistant_id=assistant_id, mcp_servers=mcp_servers)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid assistant ID")
    except Exception as e:
        logger.error(f"Failed to fetch MCP servers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


def _get_connection_config(
    mcp_server: DbMCPServer, is_admin: bool, user: User | None, db_session: Session
) -> MCPConnectionConfig | None:
    """
    Get the connection config for an MCP server.
    is_admin is true when we want the config used for the admin panel

    """
    if mcp_server.auth_type == MCPAuthenticationType.NONE:
        return None

    if (
        mcp_server.auth_type == MCPAuthenticationType.API_TOKEN
        and mcp_server.auth_performer == MCPAuthenticationPerformer.ADMIN
    ):
        connection_config = mcp_server.admin_connection_config
    else:
        user_email = user.email if user else ""
        connection_config = get_user_connection_config(
            server_id=mcp_server.id, user_email=user_email, db_session=db_session
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
    user: User | None = Depends(current_curator_or_admin_user),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, True, user)


@router.get("/server/{server_id}/tools")
def user_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
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
            enabled=False,
        )
        new_tool.display_name = display_name
        new_tool.mcp_input_schema = input_schema
        db_dirty = True
    return db_dirty


def _list_mcp_tools_by_id(
    server_id: int,
    db: Session,
    is_admin: bool,
    user: User | None,
) -> MCPToolListResponse:
    """List available tools from an existing MCP server"""
    logger.info(f"Listing tools for MCP server: {server_id}")

    try:
        # Get the MCP server
        mcp_server = get_mcp_server_by_id(server_id, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    # Get connection config based on auth type
    # TODO: for now, only the admin that set up a per-user api key server can
    # see their configuration. This is probably not ideal. Other admins
    # can of course put their own credentials in and list the tools.
    connection_config = _get_connection_config(mcp_server, is_admin, user, db)

    if not connection_config and mcp_server.auth_type != MCPAuthenticationType.NONE:
        raise HTTPException(
            status_code=401,
            detail="This MCP server is not configured yet",
        )

    user_id = str(user.id) if user else ""
    # Discover tools from the MCP server
    auth = None
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
    import time

    t1 = time.time()
    logger.info(f"Discovering tools for MCP server: {mcp_server.name}: {t1}")
    # Normalize URL to include trailing slash to avoid redirect/slow path handling
    server_url = mcp_server.server_url.rstrip("/") + "/"
    discovered_tools = discover_mcp_tools(
        server_url,
        connection_config.config.get("headers", {}) if connection_config else {},
        transport=mcp_server.transport,
        auth=auth,
    )
    logger.info(
        f"Discovered {len(discovered_tools)} tools for MCP server: {mcp_server.name}: {time.time() - t1}"
    )

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
    user: User | None,
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
        client_info = None
        if mcp_server.admin_connection_config:
            client_info_raw = mcp_server.admin_connection_config.config.get(
                MCPOAuthKeys.CLIENT_INFO.value
            )
            if client_info_raw:
                client_info = OAuthClientInformationFull.model_validate(client_info_raw)

        changing_connection_config = (
            not mcp_server.admin_connection_config
            or (
                request.auth_type == MCPAuthenticationType.OAUTH
                and (
                    client_info is None
                    or request.oauth_client_id != client_info.client_id
                    or request.oauth_client_secret != (client_info.client_secret or "")
                )
            )
            or (request.auth_type == MCPAuthenticationType.API_TOKEN)
            or (request.transport != mcp_server.transport)
        )

        # Cleanup: Delete existing connection configs
        if changing_connection_config and mcp_server.admin_connection_config_id:
            delete_connection_config(mcp_server.admin_connection_config_id, db_session)
            if user and user.email:
                delete_user_connection_configs_for_server(
                    mcp_server.id, user.email, db_session
                )

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
            f"Updated existing MCP server '{request.name}' with ID {mcp_server.id}"
        )

    else:
        # Handle new server creation
        # Prevent duplicate server creation with same URL
        normalized_url = (request.server_url or "").strip()
        if not normalized_url:
            raise HTTPException(status_code=400, detail="server_url is required")

        if not user or not user.email:
            raise HTTPException(
                status_code=400,
                detail="Authenticated user email required to create MCP servers",
            )

        # Check existing servers for same server_url
        existing_servers = get_all_mcp_servers(db_session)
        existing_server = None
        for server in existing_servers:
            if server.server_url == normalized_url:
                existing_server = server
                break
        if existing_server:
            raise HTTPException(
                status_code=409,
                detail="An MCP server with this URL already exists for this owner",
            )

        # Create new MCP server
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email if user else "",
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
            auth_performer=request.auth_performer,
            transport=request.transport or MCPTransport.STREAMABLE_HTTP,
            db_session=db_session,
        )

        logger.info(f"Created new MCP server '{request.name}' with ID {mcp_server.id}")

    if (
        not changing_connection_config
        or request.auth_type == MCPAuthenticationType.NONE
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

            # Create template config: faithful representation of what's in the admin panel
            template_config = create_connection_config(
                config_data=MCPConnectionData(
                    headers=template_data.headers,
                    header_substitutions=request.admin_credentials,
                ),
                mcp_server_id=mcp_server.id,
                user_email="",
                db_session=db_session,
            )

            # seed the user config for this admin user
            if user:
                user_config = create_connection_config(
                    config_data=MCPConnectionData(
                        headers=_build_headers_from_template(
                            template_data, request.admin_credentials, user.email
                        ),
                        header_substitutions=request.admin_credentials,
                    ),
                    mcp_server_id=mcp_server.id,
                    user_email=user.email if user else "",
                    db_session=db_session,
                )
                user_config.mcp_server_id = mcp_server.id
            admin_connection_config_id = template_config.id
        elif request.auth_type == MCPAuthenticationType.OAUTH:
            # Create initial admin config. If client credentials were provided,
            # seed client_info so the OAuth provider can skip dynamic
            # registration; otherwise, the provider will attempt it.
            cfg: MCPConnectionData = MCPConnectionData(headers={})
            if request.oauth_client_id:

                client_info = OAuthClientInformationFull(
                    client_id=request.oauth_client_id,
                    client_secret=request.oauth_client_secret,
                    redirect_uris=[AnyUrl(f"{WEB_DOMAIN}/mcp/oauth/callback")],
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"],
                    scope=REQUESTED_SCOPE,  # TODO: allow specifying scopes?
                    # default token_endpoint_auth_method is client_secret_post
                )
                cfg[MCPOAuthKeys.CLIENT_INFO.value] = client_info.model_dump(
                    mode="json"
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
                user_email=user.email if user else "",
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
    user: User | None = Depends(current_curator_or_admin_user),
) -> MCPServer:
    """Return details for one MCP server if user has access"""
    try:
        server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(server, user)

    email = user.email if user else ""

    # TODO: user permissions per mcp server not yet implemented, for now
    # permissions are based on access to assistants
    # # Quick permission check – admin or user has access
    # if user and server not in user.accessible_mcp_servers and not user.is_superuser:
    #     raise HTTPException(status_code=403, detail="Forbidden")

    return _db_mcp_server_to_api_mcp_server(
        server, email, db_session, include_auth_config=True
    )


@admin_router.get("/servers", response_model=MCPServersResponse)
def get_mcp_servers_for_admin(
    db: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
) -> MCPServersResponse:
    """Get all MCP servers for admin display"""

    logger.info("Fetching all MCP servers for admin display")

    email = user.email if user else ""
    try:
        db_mcp_servers = get_all_mcp_servers(db)

        # Convert to API model format
        mcp_servers = [
            _db_mcp_server_to_api_mcp_server(db_server, email, db)
            for db_server in db_mcp_servers
        ]

        return MCPServersResponse(mcp_servers=mcp_servers)

    except Exception as e:
        logger.error(f"Failed to fetch MCP servers for admin: {type(e)}:{e}")
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


@admin_router.get("/server/{server_id}/db-tools")
def get_mcp_server_db_tools(
    server_id: int,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> ServerToolsResponse:
    """Get existing database tools created for an MCP server"""
    logger.info(f"Getting database tools for MCP server: {server_id}")

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
def upsert_mcp_server_with_tools(
    request: MCPToolCreateRequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
) -> MCPServerCreateResponse:
    """Create or update an MCP server and associated tools"""

    # Validate auth_performer for non-none auth types
    if request.auth_type != MCPAuthenticationType.NONE and not request.auth_performer:
        raise HTTPException(
            status_code=400, detail="auth_performer is required for non-none auth types"
        )

    try:
        mcp_server = _upsert_mcp_server(request, db_session, user)

        if (
            request.auth_type != MCPAuthenticationType.NONE
            and mcp_server.admin_connection_config_id is None
        ):
            raise HTTPException(
                status_code=500, detail="Failed to set admin connection config"
            )
        db_session.commit()

        action_verb = "Updated" if request.existing_server_id else "Created"
        logger.info(
            f"{action_verb} MCP server '{request.name}' with ID {mcp_server.id}"
        )

        return MCPServerCreateResponse(
            server_id=mcp_server.id,
            server_name=mcp_server.name,
            server_url=mcp_server.server_url,
            auth_type=mcp_server.auth_type,
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
    user: User | None = Depends(current_curator_or_admin_user),
) -> MCPServerUpdateResponse:
    """Update an MCP server and associated tools"""

    try:
        mcp_server = get_mcp_server_by_id(request.server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    _ensure_mcp_server_owner_or_admin(mcp_server, user)

    if (
        mcp_server.admin_connection_config_id is None
        and mcp_server.auth_type != MCPAuthenticationType.NONE
    ):
        raise HTTPException(
            status_code=400, detail="MCP server has no admin connection config"
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
        updated_tools=updated_tools,
    )


@admin_router.delete("/server/{server_id}")
def delete_mcp_server_admin(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
) -> dict:
    """Delete an MCP server and cascading related objects (tools, configs)."""
    try:
        # Ensure it exists
        server = get_mcp_server_by_id(server_id, db_session)

        _ensure_mcp_server_owner_or_admin(server, user)

        # Log tools that will be deleted for debugging
        tools_to_delete = get_tools_by_mcp_server_id(server_id, db_session)
        logger.info(
            f"Deleting MCP server {server_id} ({server.name}) with {len(tools_to_delete)} tools"
        )
        for tool in tools_to_delete:
            logger.debug(f"  - Tool to delete: {tool.name} (ID: {tool.id})")

        # Cascade behavior handled by FK ondelete in DB
        delete_mcp_server(server_id, db_session)

        # Verify tools were deleted
        remaining_tools = get_tools_by_mcp_server_id(server_id, db_session)
        if remaining_tools:
            logger.error(
                f"WARNING: {len(remaining_tools)} tools still exist after deleting MCP server {server_id}"
            )
            # Manually delete them as a fallback
            for tool in remaining_tools:
                logger.info(
                    f"Manually deleting orphaned tool: {tool.name} (ID: {tool.id})"
                )
                delete_tool__no_commit(tool.id, db_session)
        db_session.commit()

        return {"success": True}
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except Exception as e:
        logger.error(f"Failed to delete MCP server {server_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete MCP server")
