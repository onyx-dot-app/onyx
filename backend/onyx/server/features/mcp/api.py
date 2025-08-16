import base64
import hashlib
import random
import string
from secrets import token_urlsafe
from typing import Any
from typing import cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.mcp import create_connection_config
from onyx.db.mcp import create_mcp_server
from onyx.db.mcp import delete_connection_config
from onyx.db.mcp import delete_mcp_server
from onyx.db.mcp import delete_user_connection_configs_for_server
from onyx.db.mcp import get_all_mcp_servers
from onyx.db.mcp import get_mcp_server_auth_performer
from onyx.db.mcp import get_mcp_server_by_id
from onyx.db.mcp import get_mcp_servers_for_persona
from onyx.db.mcp import get_server_auth_template
from onyx.db.mcp import get_user_connection_config
from onyx.db.mcp import update_connection_config
from onyx.db.mcp import update_mcp_server
from onyx.db.mcp import upsert_user_connection_config
from onyx.db.models import MCPConnectionConfig
from onyx.db.models import MCPServer as DbMCPServer
from onyx.db.models import User
from onyx.db.tools import create_tool__no_commit
from onyx.db.tools import delete_tool
from onyx.db.tools import get_tools_by_mcp_server_id
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.standard_oauth import _OAUTH_STATE_EXPIRATION_SECONDS
from onyx.server.documents.standard_oauth import _OAUTH_STATE_KEY_FMT
from onyx.server.features.mcp.models import MCPApiKeyResponse
from onyx.server.features.mcp.models import MCPAuthTemplate
from onyx.server.features.mcp.models import MCPConnectionData
from onyx.server.features.mcp.models import MCPDynamicClientRegistrationRequest
from onyx.server.features.mcp.models import MCPDynamicClientRegistrationResponse
from onyx.server.features.mcp.models import MCPOAuthCallbackResponse
from onyx.server.features.mcp.models import MCPServer
from onyx.server.features.mcp.models import MCPServerCreateResponse
from onyx.server.features.mcp.models import MCPServersResponse
from onyx.server.features.mcp.models import MCPServerUpdateResponse
from onyx.server.features.mcp.models import MCPToolCreateRequest
from onyx.server.features.mcp.models import MCPToolListResponse
from onyx.server.features.mcp.models import MCPToolUpdateRequest
from onyx.server.features.mcp.models import MCPUserCredentialsRequest
from onyx.server.features.mcp.models import MCPUserOAuthInitiateRequest
from onyx.server.features.mcp.models import MCPUserOAuthInitiateResponse
from onyx.tools.tool_implementations.mcp.mcp_client import discover_mcp_tools
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/mcp")
admin_router = APIRouter(prefix="/admin/mcp")
STATE_TTL_SECONDS = 60 * 15  # 15 minutes


def generate_state() -> str:
    """Generate a random state parameter for OAuth"""
    return "".join(random.choices(string.ascii_letters + string.digits, k=15))


def _parse_www_authenticate(header_value: str) -> str:
    """Parse a WWW-Authenticate header into a dict of scheme/params.

    Example: 'Bearer realm="example", authorization_uri="https://as.example/.well-known/..."'
    Returns only the parameter map, lower-cased keys.
    """
    params: dict[str, str] = {}
    try:
        # Split off auth scheme (e.g., Bearer, DPoP)
        parts = header_value.split(" ", 1)
        rest = parts[1] if len(parts) > 1 else header_value
        for item in rest.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                k = k.strip().lower()
                v = v.strip().strip('"')
                if "bearer" in k and "resource" in k:
                    return v
                params[k] = v
    except Exception:
        logger.exception(f"Failed to parse WWW-Authenticate header: {header_value}")
    return ""


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
    transport: str = "streamable-http",
) -> tuple[bool, str]:
    """Test if credentials work by calling the MCP server's tools/list endpoint"""
    try:
        # Attempt to discover tools using the provided credentials
        tools = discover_mcp_tools(server_url, connection_headers, transport=transport)

        if (
            tools is not None and len(tools) >= 0
        ):  # Even 0 tools is a successful connection
            return True, f"Successfully connected. Found {len(tools)} tools."
        else:
            return False, "Failed to retrieve tools list from server."

    except Exception as e:
        logger.error(f"Failed to test MCP server credentials: {e}")

        # Per MCP Authorization spec, on 401 the server MUST include
        # a WWW-Authenticate header pointing to resource metadata (RFC9728 §5.1).
        # Attempt an unauthenticated probe to discover that header and extract
        # an authorization/resource metadata URL for next steps.
        try:

            # Probe without auth to trigger 401 + WWW-Authenticate
            probe_url = server_url
            if "?" not in probe_url:
                # include transport hint if needed
                probe_url = (
                    probe_url.rstrip("/")
                    + "?"
                    + urlencode({"transportType": transport})
                )

            with httpx.Client(timeout=5.0, follow_redirects=False) as client:
                resp = client.get(probe_url)
                www = resp.headers.get("WWW-Authenticate") or resp.headers.get(
                    "www-authenticate"
                )
                if resp.status_code == 401 and www:
                    auth_meta_url = _parse_www_authenticate(www)
                    # Common keys per RFCs: authorization, authorization_uri, as_uri, resource,
                    # or link to resource metadata
                    # auth_meta_url = (
                    #     meta.get("authorization")
                    #     or meta.get("authorization_uri")
                    #     or meta.get("as_uri")
                    #     or meta.get("authorization_server")
                    #     or meta.get("resource_metadata")
                    #     or meta.get("resource_server")
                    # )
                    if auth_meta_url:
                        return False, (
                            "Unauthorized (401). Server advertised authorization metadata; "
                            f"next discover at: {auth_meta_url}"
                        )
                    # If no explicit URL, still include parsed params for operator visibility
        except Exception as d_err:
            logger.debug(f"Discovery probe after 401 failed: {d_err}")

        return False, f"Connection failed: {str(e)}"


# TODO: make this work
def _get_or_register_oauth_client(
    mcp_server: DbMCPServer,
    authorization_server_url: str,
    db: Session,
) -> tuple[str, str | None]:
    """Get existing OAuth client registration or dynamically register a new one.

    Returns (client_id, client_secret) tuple.
    """
    # Check if we already have a registered client for this authorization server
    admin_config = mcp_server.admin_connection_config
    if admin_config and admin_config.config:
        config = admin_config.config
        if isinstance(config, dict) and config.get("client_id"):
            # We have a previously registered client
            return config["client_id"], config.get("client_secret")

    # Need to dynamically register a client
    import os

    # Discover registration endpoint from authorization server metadata
    # Per RFC 8414, the metadata should be at .well-known/oauth-authorization-server
    metadata_url = (
        authorization_server_url.rstrip("/") + "/.well-known/oauth-authorization-server"
    )

    try:
        with httpx.Client(timeout=10.0) as client:
            # Get authorization server metadata
            resp = client.get(metadata_url)
            if resp.status_code == 404:
                # Try alternative location
                metadata_url = (
                    authorization_server_url.rstrip("/")
                    + "/.well-known/openid-configuration"
                )
                resp = client.get(metadata_url)

            if resp.status_code != 200:
                logger.warning(
                    f"Could not fetch authorization server metadata from {metadata_url}"
                )
                # Fall back to environment variables
                client_id = os.getenv("MCP_OAUTH_CLIENT_ID", "test-client-id")
                client_secret = os.getenv(
                    "MCP_OAUTH_CLIENT_SECRET", "test-client-secret"
                )
                return client_id, client_secret

            metadata = resp.json()
            registration_endpoint = metadata.get("registration_endpoint")

            if not registration_endpoint:
                logger.warning(
                    "Authorization server does not advertise registration endpoint"
                )
                # Fall back to environment variables
                client_id = os.getenv("MCP_OAUTH_CLIENT_ID", "test-client-id")
                client_secret = os.getenv(
                    "MCP_OAUTH_CLIENT_SECRET", "test-client-secret"
                )
                return client_id, client_secret

            # Register a new client per RFC 7591
            redirect_uri = os.getenv(
                "MCP_OAUTH_REDIRECT_URI",
                "http://localhost:8000/api/mcp/oauth/callback",
            )

            registration_request = {
                "application_type": "web",
                "redirect_uris": [redirect_uri],
                "client_name": f"Onyx MCP Client for {mcp_server.name}",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": os.getenv("MCP_OAUTH_SCOPE", "mcp:use"),
                "token_endpoint_auth_method": "client_secret_post",
            }

            reg_resp = client.post(
                registration_endpoint,
                json=registration_request,
                headers={"Content-Type": "application/json"},
            )

            if reg_resp.status_code not in (200, 201):
                logger.error(f"Dynamic client registration failed: {reg_resp.text}")
                # Fall back to environment variables
                client_id = os.getenv("MCP_OAUTH_CLIENT_ID", "test-client-id")
                client_secret = os.getenv(
                    "MCP_OAUTH_CLIENT_SECRET", "test-client-secret"
                )
                return client_id, client_secret

            reg_data = reg_resp.json()
            client_id = reg_data.get("client_id")
            client_secret = reg_data.get("client_secret")

            # Ensure we have a valid client_id
            if not client_id or not isinstance(client_id, str):
                logger.error(f"Invalid client_id in registration response: {client_id}")
                # Fall back to environment variables
                client_id = os.getenv("MCP_OAUTH_CLIENT_ID", "test-client-id")
                client_secret = os.getenv(
                    "MCP_OAUTH_CLIENT_SECRET", "test-client-secret"
                )
                return client_id, client_secret

            # Store the registered client info in the admin connection config
            if not admin_config:
                admin_config = create_connection_config(
                    mcp_server_id=mcp_server.id,
                    user_email="",  # Admin config
                    config_data=MCPConnectionData(
                        client_id=client_id,
                        client_secret=client_secret
                        or "",  # Provide empty string if None
                        registration_access_token=reg_data.get(
                            "registration_access_token"
                        ),
                        registration_client_uri=reg_data.get("registration_client_uri"),
                        headers={},
                    ),
                    db_session=db,
                )
                mcp_server.admin_connection_config = admin_config
            else:
                # Update existing config with client registration
                if not admin_config.config:
                    admin_config.config = {}
                admin_config.config.update(
                    {
                        "client_id": client_id,
                        "client_secret": client_secret
                        or "",  # Provide empty string if None
                        "registration_access_token": reg_data.get(
                            "registration_access_token"
                        ),
                        "registration_client_uri": reg_data.get(
                            "registration_client_uri"
                        ),
                    }
                )

            db.add(admin_config)
            db.commit()

            logger.info(
                f"Successfully registered OAuth client for {mcp_server.name}: {client_id}"
            )
            return client_id, client_secret

    except Exception as e:
        logger.error(f"Failed to register OAuth client: {e}")
        # Fall back to environment variables
        return (
            os.getenv("MCP_OAUTH_CLIENT_ID", "test-client-id"),
            os.getenv("MCP_OAUTH_CLIENT_SECRET", "test-client-secret"),
        )


@router.post("/oauth/register", response_model=MCPDynamicClientRegistrationResponse)
def register_oauth_client(
    request: MCPDynamicClientRegistrationRequest,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> MCPDynamicClientRegistrationResponse:
    """Manually trigger dynamic client registration for an MCP server."""

    try:
        mcp_server = get_mcp_server_by_id(request.server_id, db)
    except Exception:
        raise HTTPException(status_code=404, detail="MCP server not found")

    client_id, client_secret = _get_or_register_oauth_client(
        mcp_server, request.authorization_server_url, db
    )

    return MCPDynamicClientRegistrationResponse(
        client_id=client_id,
        client_secret=client_secret,
        registration_access_token=None,  # Not exposed via API for security
        registration_client_uri=None,  # Not exposed via API for security
    )


def fetch_json(url: str) -> dict:
    with httpx.Client(timeout=15.0) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def fetch_as_metadata(issuer: str) -> dict:
    # RFC 8414 discovery
    # Try the OAuth AS metadata path first; fall back to OIDC if needed
    urls = [
        f"{issuer}/.well-known/oauth-authorization-server",
        f"{issuer}/.well-known/openid-configuration",
    ]
    for u in urls:
        try:
            return fetch_json(u)
        except Exception as e:
            logger.debug(f"Failed to fetch authorization server metadata from {u}: {e}")
    raise RuntimeError("Could not fetch authorization server metadata")


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    verifier = b64url(token_urlsafe(64).encode())
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class MCPOauthState(BaseModel):
    server_id: int
    verifier: str
    return_path: str
    token_endpoint: str
    is_admin: bool


def redis_state_key(state: str) -> str:
    return _OAUTH_STATE_KEY_FMT.format(state=state)


@admin_router.post("/oauth/initiate", response_model=MCPUserOAuthInitiateResponse)
def initiate_admin_oauth(
    request: MCPUserOAuthInitiateRequest,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> MCPUserOAuthInitiateResponse:
    """Initiate OAuth flow for admin MCP server authentication"""
    return _initiate_oauth(request, db, is_admin=True)


@router.post("/oauth/initiate", response_model=MCPUserOAuthInitiateResponse)
def initiate_user_oauth(
    request: MCPUserOAuthInitiateRequest,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> MCPUserOAuthInitiateResponse:
    return _initiate_oauth(request, db, is_admin=False)


def _initiate_oauth(
    request: MCPUserOAuthInitiateRequest,
    db: Session,
    is_admin: bool,
) -> MCPUserOAuthInitiateResponse:
    """Initiate OAuth flow for per-user MCP server authentication"""

    logger.info(f"Initiating per-user OAuth for server: {request.server_id}")

    try:
        server_id = int(request.server_id)
        mcp_server = get_mcp_server_by_id(server_id, db)
    except Exception:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if mcp_server.auth_type != MCPAuthenticationType.OAUTH:
        raise HTTPException(
            status_code=400,
            detail=f"Server was configured with authentication type {mcp_server.auth_type.value}",
        )
    if (
        mcp_server.admin_connection_config is None
        or mcp_server.admin_connection_config.config.get("client_id") is None
    ):
        raise HTTPException(
            status_code=400,
            detail="MCP server is not configured with an OAuth client ID",
        )

    # Step 1: make unauthenticated request and parse returned www authenticate header
    # Ensure we have a trailing slash for the MCP endpoint
    probe_url = mcp_server.server_url.rstrip("/") + "/"
    logger.info(f"Probing OAuth server at: {probe_url}")

    auth_info = ""
    auth_server_url = ""
    scopes = []
    with httpx.Client(timeout=5.0, follow_redirects=True) as client:
        resp = client.post(probe_url)  # POST for MCP streamable-http

        if resp.status_code == 401:

            # 401 means we need to authenticate
            auth_info = _parse_www_authenticate(resp.headers["WWW-Authenticate"])
            logger.info(f"WWW-Authenticate header: {auth_info}")

            well_known_resp = client.get(auth_info)
            logger.info(f"Response: {well_known_resp.text}")
            wk_json = well_known_resp.json()
            as_uris = wk_json.get("authorization_servers", [])
            if not as_uris:
                raise HTTPException(
                    status_code=400,
                    detail="No authorization servers retrieved from MCP resource discovery",
                )
            auth_server_url = as_uris[0]
            logger.info(f"Authorization server URL: {auth_server_url}")
            scopes = wk_json.get("scopes_supported", [])
            logger.info(f"Scopes: {scopes}")

    issuer_meta = fetch_as_metadata(auth_server_url)

    authz_ep = issuer_meta["authorization_endpoint"]
    token_ep = issuer_meta["token_endpoint"]
    logger.info(f"Authorization endpoint: {authz_ep}")
    logger.info(f"Token endpoint: {token_ep}")

    if not authz_ep or not token_ep:
        raise HTTPException(
            status_code=400,
            detail="No authorization or token endpoint found in authorization server metadata",
        )

    verifier, challenge = make_pkce_pair()
    state = token_urlsafe(24)
    scope_str = " ".join(scopes)
    redis_client = get_redis_client()
    state_data = MCPOauthState(
        server_id=int(request.server_id),
        verifier=verifier,
        return_path=request.return_path,
        token_endpoint=token_ep,
        is_admin=is_admin,
    )
    redis_client.set(
        redis_state_key(state),
        state_data.model_dump_json(),
        ex=_OAUTH_STATE_EXPIRATION_SECONDS,
    )

    redirect_uri = f"{WEB_DOMAIN}/mcp/oauth/callback"

    # Build authorization URL
    authz_params = {
        "response_type": "code",
        "client_id": mcp_server.admin_connection_config.config.get("client_id"),
        "redirect_uri": redirect_uri,
        "scope": scope_str,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    # Many AS’s (and the MCP OAuth guidance) support binding tokens to the resource URL.
    if request.include_resource_param:
        authz_params["resource"] = (
            mcp_server.server_url
        )  # ignored if server doesn’t support RFC 8707

    authz_url = f"{authz_ep}?{urlencode(authz_params)}"

    logger.info(f"Generated OAuth URL: {authz_url}")

    return MCPUserOAuthInitiateResponse(
        oauth_url=authz_url,
        state=state,
        server_id=int(request.server_id),
        server_name=mcp_server.name,
        code_verifier=verifier,
    )


@router.post("/oauth/callback", response_model=MCPOAuthCallbackResponse)
def process_oauth_callback(
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
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code parameter")
    stored_data = cast(bytes, redis_client.get(redis_state_key(state)))
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

    if not mcp_server.admin_connection_config:
        raise HTTPException(
            status_code=400,
            detail="Server referenced by callback is not configured, try recreating",
        )
    client_id = mcp_server.admin_connection_config.config.get("client_id")
    client_secret = mcp_server.admin_connection_config.config.get("client_secret")
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="No client ID or secret found")

    if mcp_server.auth_type != MCPAuthenticationType.OAUTH.value:
        raise HTTPException(status_code=400, detail="Server is not OAuth-enabled")

    email = user.email if user else ""

    redirect_uri = f"{WEB_DOMAIN}/mcp/oauth/callback"

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": state_data.verifier,
        # optional if using resource indicators:
        "resource": mcp_server.server_url,
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    with httpx.Client(timeout=30) as client:
        # confidential client → HTTP Basic
        resp = client.post(
            state_data.token_endpoint,
            data=form,
            headers=headers,
            auth=(client_id, client_secret),
        )
        resp.raise_for_status()
        token_payload = resp.json()
        access_token = token_payload.get("access_token")
        refresh_token = token_payload.get("refresh_token")
        token_type = token_payload.get("token_type", "Bearer")

    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in OAuth response")

    # Persist tokens in user's connection config
    config_data: dict[str, Any] = {
        "access_token": access_token,
        "token_type": token_type,
    }
    if refresh_token:
        config_data["refresh_token"] = refresh_token

    cfg_headers = {"Authorization": f"{token_type} {access_token}"}

    cfg = MCPConnectionData(
        headers=cfg_headers,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        header_substitutions={},
    )

    upsert_user_connection_config(
        server_id=mcp_server.id,
        user_email=email,
        config_data=cfg,
        db_session=db_session,
    )

    if state_data.is_admin:
        update_connection_config(
            mcp_server.admin_connection_config.id,
            db_session,
            cfg,
        )

    db_session.commit()

    # Optionally validate by listing tools
    validated = False
    try:
        is_valid, _ = test_mcp_server_credentials(
            mcp_server.server_url,
            {"Authorization": f"{token_type} {access_token}"},
            "streamable-http",  # TODO: make configurable?
        )
        validated = is_valid
    except Exception as e:
        logger.warning(f"Could not validate OAuth token with MCP server: {e}")

    logger.info(
        f"OAuth tokens saved: {validated} "
        f"server_id={str(mcp_server.id)} "
        f"server_name={mcp_server.name} "
        f"return_path={state_data.return_path}"
    )

    # Return typed response for the frontend API call
    return MCPOAuthCallbackResponse(
        success=True,
        server_id=mcp_server.id,
        server_name=mcp_server.name,
        authenticated=validated,
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
                header_substitutions=auth_template.config.get(
                    "header_substitutions", {}
                ),
                client_id=auth_template.config.get("client_id", ""),
                client_secret=auth_template.config.get("client_secret", ""),
                registration_access_token=auth_template.config.get(
                    "registration_access_token", ""
                ),
                registration_client_uri=auth_template.config.get(
                    "registration_client_uri", ""
                ),
            )
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
        is_valid, test_message = test_mcp_server_credentials(
            mcp_server.server_url, config_data["headers"], transport=request.transport
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


def _db_mcp_server_to_api_mcp_server(
    db_server: DbMCPServer, email: str, db: Session, include_auth_config: bool = False
) -> MCPServer:
    """Convert database MCP server to API model"""

    # Determine auth performer based on whether per_user_template exists
    auth_performer = get_mcp_server_auth_performer(db_server)

    # Check if user has authentication configured and extract credentials
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
                admin_credentials = {
                    "client_id": db_server.admin_connection_config.config["client_id"],
                    "client_secret": db_server.admin_connection_config.config[
                        "client_secret"
                    ],
                }
    else:  # currently: per user auth using api key OR oauth
        user_config = get_user_connection_config(db_server.id, email, db)
        user_authenticated = user_config is not None

        # Test existing credentials if they exist
        if user_authenticated and user_config:
            try:
                is_valid, _ = test_mcp_server_credentials(
                    db_server.server_url, user_config.config.get("headers", {})
                )
                user_authenticated = is_valid
                if (
                    include_auth_config
                    and db_server.auth_type != MCPAuthenticationType.OAUTH
                ):
                    user_credentials = user_config.config.get(
                        "header_substitutions", {}
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to test user credentials for server {db_server.name}: {e}"
                )
                # Keep user_authenticated as True if we can't test, to avoid breaking existing flows

        if (
            db_server.auth_type == MCPAuthenticationType.OAUTH
            and db_server.admin_connection_config
        ):
            admin_credentials = {
                "client_id": db_server.admin_connection_config.config["client_id"],
                "client_secret": db_server.admin_connection_config.config[
                    "client_secret"
                ],
            }

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
        auth_type=db_server.auth_type,
        auth_performer=auth_performer,
        is_authenticated=is_authenticated,
        user_authenticated=user_authenticated,
        auth_template=auth_template,
        user_credentials=user_credentials,
        admin_credentials=admin_credentials,
    )


@router.get("/servers/{assistant_id}", response_model=MCPServersResponse)
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
        mcp_servers: list[MCPServer] = []
        for db_server in db_mcp_servers:
            # TODO: oauth stuff
            # if db_server.auth_type == MCPAuthenticationType.OAUTH.value:
            #     # Try refresh if we have refresh token
            #     user_cfg = get_user_connection_config(db_server.id, email, db)
            #     if user_cfg and isinstance(user_cfg.config, dict):
            #         cfg = user_cfg.config
            #         if cfg.get("refresh_token"):
            #             # Get client credentials from admin config if available
            #             client_id = None
            #             client_secret = None
            #             admin_cfg = db_server.admin_connection_config
            #             if admin_cfg and admin_cfg.config and isinstance(admin_cfg.config, dict):
            #                 client_id = admin_cfg.config.get("client_id")
            #                 client_secret = admin_cfg.config.get("client_secret")

            #             token_payload = refresh_oauth_token(
            #                 db_server.server_url,
            #                 cfg,
            #                 client_id=client_id,
            #                 client_secret=client_secret,
            #             )
            #             if token_payload and token_payload.get("access_token"):
            #                 # Update stored tokens and headers
            #                 access_token = token_payload["access_token"]
            #                 token_type = token_payload.get("token_type", "Bearer")
            #                 refresh_token = token_payload.get("refresh_token") or cfg.get("refresh_token")
            #                 user_cfg.config.update(
            #                     {
            #                         "access_token": access_token,
            #                         "refresh_token": refresh_token,
            #                         "token_type": token_type,
            #                         "headers": {"Authorization": f"{token_type} {access_token}"},
            #                     }
            #                 )
            #                 db.add(user_cfg)
            #                 db.commit()

            mcp_servers.append(_db_mcp_server_to_api_mcp_server(db_server, email, db))

        return MCPServersResponse(assistant_id=assistant_id, mcp_servers=mcp_servers)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid assistant ID")
    except Exception as e:
        logger.error(f"Failed to fetch MCP servers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch MCP servers")


@admin_router.get("/server/{server_id}/tools")
def admin_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, True, user)


@router.get("/server/{server_id}/tools")
def user_list_mcp_tools_by_id(
    server_id: int,
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> MCPToolListResponse:
    return _list_mcp_tools_by_id(server_id, db, False, user)


def _get_connection_config(
    mcp_server: DbMCPServer, is_admin: bool, user: User | None, db_session: Session
) -> MCPConnectionConfig | None:
    """Get the connection config for an MCP server"""
    if mcp_server.auth_type == MCPAuthenticationType.NONE:
        return None

    if (
        mcp_server.auth_type == MCPAuthenticationType.API_TOKEN
        and get_mcp_server_auth_performer(mcp_server)
        == MCPAuthenticationPerformer.ADMIN
    ) or (mcp_server.auth_type == MCPAuthenticationType.OAUTH and is_admin):
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

    # Get connection config based on auth type
    # TODO: for now, only the admin that set up a per-user api key server can
    # see their configuration. This is probably not ideal. Other admins
    # can of course put their own credentials in and list the tools.
    connection_config = _get_connection_config(mcp_server, is_admin, user, db)

    # Discover tools from the MCP server
    tools = discover_mcp_tools(
        mcp_server.server_url,
        connection_config.config.get("headers", {}) if connection_config else {},
    )

    # TODO: Also list resources from the MCP server
    # resources = discover_mcp_resources(mcp_server, connection_config)

    return MCPToolListResponse(
        server_id=server_id,
        server_name=mcp_server.name,
        server_url=mcp_server.server_url,
        tools=tools,
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
        changing_connection_config = (
            not mcp_server.admin_connection_config
            or (
                request.auth_type == MCPAuthenticationType.OAUTH
                and (
                    request.oauth_client_id
                    != mcp_server.admin_connection_config.config["client_id"]
                    or request.oauth_client_secret
                    != mcp_server.admin_connection_config.config["client_secret"]
                )
            )
            or (request.auth_type == MCPAuthenticationType.API_TOKEN)
        )

        # Cleanup: Delete existing connection configs
        if changing_connection_config and mcp_server.admin_connection_config_id:
            delete_connection_config(mcp_server.admin_connection_config_id, db_session)
            if user and user.email:
                delete_user_connection_configs_for_server(
                    mcp_server.id, user.email, db_session
                )

        # Update the server with new values
        mcp_server = update_mcp_server(
            server_id=request.existing_server_id,
            db_session=db_session,
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
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
        mcp_server = create_mcp_server(
            owner_email=user.email if user else "",
            name=request.name,
            description=request.description,
            server_url=request.server_url,
            auth_type=request.auth_type,
            db_session=db_session,
        )

        logger.info(f"Created new MCP server '{request.name}' with ID {mcp_server.id}")

    if not changing_connection_config:
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
            assert request.oauth_client_id and request.oauth_client_secret
            admin_config = create_connection_config(
                config_data=MCPConnectionData(
                    client_id=request.oauth_client_id,
                    client_secret=request.oauth_client_secret,
                    headers={},  # will be set during oauth connection flow
                ),
                mcp_server_id=mcp_server.id,
                user_email="",
                db_session=db_session,
            )
            admin_connection_config_id = admin_config.id
    elif request.auth_performer == MCPAuthenticationPerformer.ADMIN:
        raise HTTPException(
            status_code=400,
            detail="Admin authentication is not yet supported for MCP servers: user per-user",
        )

    # Update server with config IDs
    if admin_connection_config_id is not None:
        mcp_server = update_mcp_server(
            server_id=mcp_server.id,
            db_session=db_session,
            admin_connection_config_id=admin_connection_config_id,
        )

    return mcp_server


def _add_tools_to_server(
    mcp_server: DbMCPServer,
    selected_tools: list[str],
    keep_tool_names: set[str],
    user: User | None,
    db_session: Session,
) -> int:
    created_tools = 0
    # First, discover available tools from the server to get full definitions
    # TODO: make this configurable
    transport = "streamable-http"

    connection_config = _get_connection_config(mcp_server, True, user, db_session)
    headers = connection_config.config.get("headers", {}) if connection_config else {}

    available_tools = discover_mcp_tools(
        mcp_server.server_url, headers, transport=transport
    )
    tools_by_name = {tool.name: tool for tool in available_tools}

    for tool_name in selected_tools:
        if tool_name not in tools_by_name:
            logger.warning(f"Tool '{tool_name}' not found in MCP server")
            continue

        if tool_name in keep_tool_names:
            # tool was not deleted earlier and not added now
            continue

        tool_def = tools_by_name[tool_name]

        # Create Tool entry for each selected tool
        tool = create_tool__no_commit(
            name=tool_name,
            description=tool_def.description,
            openapi_schema=None,  # MCP tools don't use OpenAPI
            custom_headers=None,
            user_id=user.id if user else None,
            db_session=db_session,
            passthrough_auth=False,
        )

        # Update the tool with MCP server ID, display name, and input schema
        tool.mcp_server_id = mcp_server.id
        annotations_title = tool_def.annotations.title if tool_def.annotations else None
        tool.display_name = tool_def.title or annotations_title or tool_name
        tool.mcp_input_schema = tool_def.inputSchema

        created_tools += 1

        logger.info(f"Created MCP tool '{tool.name}' with ID {tool.id}")
    return created_tools


@admin_router.get("/servers/{server_id}", response_model=MCPServer)
def get_mcp_server_detail(
    server_id: int,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> MCPServer:
    """Return details for one MCP server if user has access"""
    try:
        server = get_mcp_server_by_id(server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

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
    user: User | None = Depends(current_admin_user),
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
        logger.error(f"Failed to fetch MCP servers: {e}")
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
                description=tool.description or "",
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
    user: User | None = Depends(current_admin_user),
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
    user: User | None = Depends(current_admin_user),
) -> MCPServerUpdateResponse:
    """Update an MCP server and associated tools"""

    try:
        mcp_server = get_mcp_server_by_id(request.server_id, db_session)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if (
        mcp_server.admin_connection_config_id is None
        and mcp_server.auth_type != MCPAuthenticationType.NONE
    ):
        raise HTTPException(
            status_code=400, detail="MCP server has no admin connection config"
        )

    # Cleanup: Delete tools for this server that are not in the selected_tools list
    selected_names = set(request.selected_tools or [])
    existing_tools = get_tools_by_mcp_server_id(request.server_id, db_session)
    keep_tool_names = set()
    updated_tools = 0
    for tool in existing_tools:
        if tool.name in selected_names:
            keep_tool_names.add(tool.name)
        else:
            delete_tool(tool.id, db_session)
            updated_tools += 1
    # If selected_tools is provided, create individual tools for each

    if request.selected_tools:
        updated_tools += _add_tools_to_server(
            mcp_server,
            request.selected_tools,
            keep_tool_names,
            user,
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
    db: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> dict:
    """Delete an MCP server and cascading related objects (tools, configs)."""
    try:
        # Ensure it exists
        server = get_mcp_server_by_id(server_id, db)

        # Log tools that will be deleted for debugging
        tools_to_delete = get_tools_by_mcp_server_id(server_id, db)
        logger.info(
            f"Deleting MCP server {server_id} ({server.name}) with {len(tools_to_delete)} tools"
        )
        for tool in tools_to_delete:
            logger.debug(f"  - Tool to delete: {tool.name} (ID: {tool.id})")

        # Cascade behavior handled by FK ondelete in DB
        delete_mcp_server(server_id, db)

        # Verify tools were deleted
        remaining_tools = get_tools_by_mcp_server_id(server_id, db)
        if remaining_tools:
            logger.error(
                f"WARNING: {len(remaining_tools)} tools still exist after deleting MCP server {server_id}"
            )
            # Manually delete them as a fallback
            for tool in remaining_tools:
                logger.info(
                    f"Manually deleting orphaned tool: {tool.name} (ID: {tool.id})"
                )
                delete_tool(tool.id, db)
            db.commit()

        return {"success": True}
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP server not found")
    except Exception as e:
        logger.error(f"Failed to delete MCP server {server_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete MCP server")
