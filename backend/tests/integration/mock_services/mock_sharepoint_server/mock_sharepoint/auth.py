"""The Entra token endpoint, access tokens, download URL tokens and the
credentials a connector signs in with.

Tokens are not signed. An access token has the shape of a JWT and names the
tenant, the client and the audience, so the server knows the app of each call.
"""

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pydantic import BaseModel

from .responses import MockResponse, json_response, oauth_error
from .settings import LOGIN_HOST, AuthSettings

TOKEN_LIFETIME_SECONDS = 3_599
_DEFAULT_SCOPE_SUFFIX = "/.default"
_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
_SIGNATURE = "mock-signature"


class AppToken(BaseModel):
    tenant_id: str
    client_id: str
    # The resource the token is for, such as https://graph.microsoft.com.
    audience: str
    certificate: bool
    expires_at: float

    @property
    def app(self) -> str:
        return f"{self.tenant_id}/{self.client_id}"


class DownloadToken(BaseModel):
    drive_id: str
    item_id: str
    app: str
    expires_at: float


def _b64(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def mint_access_token(
    token: AppToken, app_display_name: str, now: float | None = None
) -> str:
    issued = int(now if now is not None else time.time())
    claims = {
        "aud": token.audience,
        "iss": f"https://sts.windows.net/{token.tenant_id}/",
        "iat": issued,
        "exp": int(token.expires_at),
        "tid": token.tenant_id,
        "appid": token.client_id,
        "app_displayname": app_display_name,
        "appidacr": "2" if token.certificate else "1",
        "roles": ["Sites.Read.All", "GroupMember.Read.All"],
    }
    header = {"typ": "JWT", "alg": "none"}
    return f"{_b64(header)}.{_b64(claims)}.{_SIGNATURE}"


def parse_access_token(authorization: str | None) -> AppToken | None:
    """The app behind an Authorization header. None when the header carries no
    token of this server, or the token is expired."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    parts = authorization[7:].strip().split(".")
    if len(parts) != 3 or parts[2] != _SIGNATURE:
        return None
    claims = _unb64(parts[1])
    if claims is None:
        return None
    try:
        token = AppToken(
            tenant_id=claims["tid"],
            client_id=claims["appid"],
            audience=claims["aud"],
            certificate=claims["appidacr"] == "2",
            expires_at=float(claims["exp"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if token.expires_at <= time.time():
        return None
    return token


def mint_download_token(token: DownloadToken) -> str:
    return _b64(
        {"d": token.drive_id, "i": token.item_id, "a": token.app, "x": token.expires_at}
    )


def parse_download_token(value: str | None) -> DownloadToken | None:
    """The token of a download URL, expired or not."""
    payload = _unb64(value) if value else None
    if payload is None:
        return None
    try:
        return DownloadToken(
            drive_id=payload["d"],
            item_id=payload["i"],
            app=payload["a"],
            expires_at=float(payload["x"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def openid_configuration(tenant: str) -> dict[str, Any]:
    base = f"https://{LOGIN_HOST}/{tenant}"
    return {
        "token_endpoint": f"{base}/oauth2/v2.0/token",
        "authorization_endpoint": f"{base}/oauth2/v2.0/authorize",
        "device_authorization_endpoint": f"{base}/oauth2/v2.0/devicecode",
        "jwks_uri": f"{base}/discovery/v2.0/keys",
        "issuer": f"https://{LOGIN_HOST}/{tenant}/v2.0",
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "private_key_jwt",
            "client_secret_basic",
        ],
        "response_types_supported": ["code", "id_token", "token"],
        "subject_types_supported": ["pairwise"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "tenant_region_scope": "NA",
        "cloud_instance_name": "microsoftonline.com",
    }


def instance_discovery() -> dict[str, Any]:
    return {
        "tenant_discovery_endpoint": (
            f"https://{LOGIN_HOST}/common/v2.0/.well-known/openid-configuration"
        ),
        "api-version": "1.1",
        "metadata": [
            {
                "preferred_network": LOGIN_HOST,
                "preferred_cache": "login.windows.net",
                "aliases": [LOGIN_HOST, "login.windows.net", "login.microsoft.com"],
            }
        ],
    }


def handle_token_request(
    form: dict[str, str],
    tenant: str,
    known_tenants: frozenset[str],
    tenant_id: str,
    settings: AuthSettings,
) -> MockResponse:
    """The client credentials grant, with a client secret or a certificate
    assertion. The assertion's signature is not checked."""
    if tenant.lower() not in known_tenants:
        return oauth_error(
            400,
            "invalid_request",
            f"AADSTS90002: Tenant '{tenant}' not found. Check to make sure you "
            "have the correct tenant ID and are signing into the correct cloud.",
        )
    if form.get("grant_type") != "client_credentials":
        return oauth_error(
            400,
            "unsupported_grant_type",
            "AADSTS70003: The app requested an unsupported grant type "
            f"'{form.get('grant_type', '')}'.",
        )
    client_id = form.get("client_id", "")
    if not client_id:
        return oauth_error(
            400,
            "invalid_request",
            "AADSTS900144: The request body must contain the following "
            "parameter: 'client_id'.",
        )
    scopes = form.get("scope", "").split()
    resources = [s for s in scopes if s.endswith(_DEFAULT_SCOPE_SUFFIX)]
    if len(resources) != 1:
        return oauth_error(
            400,
            "invalid_scope",
            "AADSTS1002012: The provided value for scope is not valid. Client "
            "credential flows must have a scope value with /.default suffixed "
            "to the resource identifier.",
        )

    assertion = form.get("client_assertion")
    if assertion is not None:
        if (
            form.get("client_assertion_type") != _ASSERTION_TYPE
            or len(assertion.split(".")) != 3
        ):
            return oauth_error(
                401,
                "invalid_client",
                "AADSTS700027: Client assertion failed signature validation.",
            )
    elif form.get("client_secret") != settings.client_secret:
        return oauth_error(
            401,
            "invalid_client",
            "AADSTS7000215: Invalid client secret provided. Ensure the secret "
            "being sent in the request is the client secret value, not the "
            f"client secret ID, for a secret added to app '{client_id}'.",
        )

    now = time.time()
    token = AppToken(
        tenant_id=tenant_id,
        client_id=client_id,
        audience=resources[0][: -len(_DEFAULT_SCOPE_SUFFIX)],
        certificate=assertion is not None,
        expires_at=now + TOKEN_LIFETIME_SECONDS,
    )
    return json_response(
        200,
        {
            "token_type": "Bearer",
            "expires_in": TOKEN_LIFETIME_SECONDS,
            "ext_expires_in": TOKEN_LIFETIME_SECONDS,
            "access_token": mint_access_token(token, settings.app_display_name, now),
        },
    )


class Credentials:
    """The credentials a connector uses against this server. The certificate
    is self-signed and made on first use."""

    def __init__(self) -> None:
        self._pfx: tuple[str, str] | None = None

    def _pfx_base64(self, password: str) -> str:
        if self._pfx is not None and self._pfx[0] == password:
            return self._pfx[1]
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "onyx-mock")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .sign(key, hashes.SHA256())
        )
        pfx = pkcs12.serialize_key_and_certificates(
            b"onyx-mock",
            key,
            certificate,
            None,
            serialization.BestAvailableEncryption(password.encode()),
        )
        encoded = base64.b64encode(pfx).decode()
        self._pfx = (password, encoded)
        return encoded

    def credential_json(self, settings: AuthSettings, tenant_id: str) -> dict[str, Any]:
        """Both forms of the SharePoint credential, ready for
        `load_credentials`."""
        return {
            "client_secret": {
                "sp_client_id": settings.client_id,
                "sp_client_secret": settings.client_secret,
                "sp_directory_id": tenant_id,
            },
            "certificate": {
                "sp_client_id": settings.client_id,
                "sp_directory_id": tenant_id,
                "sp_private_key": self._pfx_base64(settings.certificate_password),
                "sp_certificate_password": settings.certificate_password,
                "authentication_method": "certificate",
            },
        }
