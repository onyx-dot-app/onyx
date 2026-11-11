"""The OAuth token endpoint and bearer-token checks.

Access tokens are stateless (`mockat.` + base64 JSON), so they stay valid
across a restart. JWT assertions are decoded but not verified: any service
account key whose client_email matches the settings works.
"""

import base64
import binascii
import json
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel

from .corpus import Corpus, stable_digits
from .responses import MockResponse, json_response, oauth_error
from .settings import SCOPE_PREFIX, FaultSettings

_ACCESS_PREFIX = "mockat."
_REFRESH_PREFIX = "mockrt."
_TOKEN_LIFETIME_SECONDS = 3600
_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"

DRIVE_METADATA_SCOPES = frozenset(
    SCOPE_PREFIX + s
    for s in (
        "drive",
        "drive.readonly",
        "drive.metadata",
        "drive.metadata.readonly",
        "drive.file",
    )
)
DRIVE_CONTENT_SCOPES = frozenset(
    SCOPE_PREFIX + s for s in ("drive", "drive.readonly", "drive.file")
)
DIRECTORY_USER_SCOPES = frozenset(
    SCOPE_PREFIX + s for s in ("admin.directory.user", "admin.directory.user.readonly")
)
DIRECTORY_GROUP_SCOPES = frozenset(
    SCOPE_PREFIX + s
    for s in (
        "admin.directory.group",
        "admin.directory.group.readonly",
        "admin.directory.group.member.readonly",
    )
)
DOCS_SCOPES = frozenset(
    SCOPE_PREFIX + s
    for s in ("documents", "documents.readonly", "drive", "drive.readonly")
)
_DEFAULT_OAUTH_SCOPES = (
    SCOPE_PREFIX + "drive.readonly",
    SCOPE_PREFIX + "drive.metadata.readonly",
    SCOPE_PREFIX + "admin.directory.group.readonly",
    SCOPE_PREFIX + "admin.directory.user.readonly",
)


class Principal(BaseModel):
    email: str
    scopes: frozenset[str]
    is_admin: bool


def _b64encode(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(text: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _issue(email: str, scopes: list[str]) -> MockResponse:
    expires_at = int(time.time()) + _TOKEN_LIFETIME_SECONDS
    token = _ACCESS_PREFIX + _b64encode({"e": email, "s": scopes, "x": expires_at})
    return json_response(
        200,
        {
            "access_token": token,
            "expires_in": _TOKEN_LIFETIME_SECONDS - 1,
            "token_type": "Bearer",
            "scope": " ".join(scopes),
        },
    )


def handle_token_request(
    form: dict[str, str], corpus: Corpus, faults: FaultSettings
) -> MockResponse:
    grant_type = form.get("grant_type", "")
    if grant_type == _JWT_BEARER:
        return _jwt_grant(form.get("assertion", ""), corpus, faults)
    if grant_type == "refresh_token":
        payload = _b64decode(
            form.get("refresh_token", "").removeprefix(_REFRESH_PREFIX)
        )
        email = payload.get("e") if payload else None
        if not isinstance(email, str) or email not in corpus.users:
            return oauth_error(
                400, "invalid_grant", "Token has been expired or revoked."
            )
        requested = form.get("scope", "").split()
        return _issue(email, requested or list(_DEFAULT_OAUTH_SCOPES))
    return oauth_error(
        400, "unsupported_grant_type", f"Invalid grant_type: {grant_type}"
    )


def _jwt_grant(assertion: str, corpus: Corpus, faults: FaultSettings) -> MockResponse:
    parts = assertion.split(".")
    claims = _b64decode(parts[1]) if len(parts) == 3 else None
    if claims is None or claims.get("iss") != faults.service_account_email:
        return oauth_error(400, "invalid_grant", "Invalid JWT Signature.")
    scopes = str(claims.get("scope", "")).split()
    subject = claims.get("sub")
    if subject is None:
        # The service account acting as itself, without domain-wide delegation.
        return _issue(faults.service_account_email, scopes)
    if faults.granted_scopes is not None and not set(scopes) <= set(
        faults.granted_scopes
    ):
        return oauth_error(
            401,
            "unauthorized_client",
            "Client is unauthorized to retrieve access tokens using this method, "
            "or client not authorized for any of the scopes requested.",
        )
    if not isinstance(subject, str) or subject not in corpus.users:
        return oauth_error(400, "invalid_grant", "Invalid email or User ID")
    return _issue(subject, scopes)


def authenticate(headers: dict[str, str], corpus: Corpus) -> Principal | None:
    authorization = headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token.startswith(_ACCESS_PREFIX):
        return None
    payload = _b64decode(token.removeprefix(_ACCESS_PREFIX))
    if payload is None or int(payload.get("x", 0)) < time.time():
        return None
    email = payload.get("e")
    scopes = payload.get("s")
    if not isinstance(email, str) or not isinstance(scopes, list):
        return None
    user = corpus.users.get(email)
    return Principal(
        email=email,
        scopes=frozenset(str(s) for s in scopes),
        is_admin=bool(user and user.is_admin),
    )


class ServiceAccountKeys:
    """One RSA key per server process; the server never checks signatures."""

    def __init__(self) -> None:
        self._pem: str | None = None
        self._key_id = secrets.token_hex(20)

    def _private_key_pem(self) -> str:
        if self._pem is None:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._pem = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()
        return self._pem

    def service_account_key(
        self, faults: FaultSettings, token_uri: str
    ) -> dict[str, str]:
        email = faults.service_account_email
        return {
            "type": "service_account",
            "project_id": email.split("@")[-1].split(".")[0],
            "private_key_id": self._key_id,
            "private_key": self._private_key_pem(),
            "client_email": email,
            "client_id": stable_digits(f"client:{email}", 21),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": token_uri,
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": (
                "https://www.googleapis.com/robot/v1/metadata/x509/"
                + email.replace("@", "%40")
            ),
            "universe_domain": "googleapis.com",
        }


def oauth_credentials(email: str, token_uri: str) -> dict[str, Any]:
    """An authorized-user token, as the OAuth consent flow would store it."""
    return {
        "client_id": "mock-client-id.apps.googleusercontent.com",
        "client_secret": "mock-client-secret",
        "refresh_token": _REFRESH_PREFIX + _b64encode({"e": email}),
        "token": None,
        "expiry": "2000-01-01T00:00:00Z",
        "token_uri": token_uri,
        "scopes": list(_DEFAULT_OAUTH_SCOPES),
    }
