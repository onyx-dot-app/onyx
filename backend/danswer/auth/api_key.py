import secrets
import uuid
from urllib.parse import quote
from urllib.parse import unquote

from fastapi import Request
from passlib.hash import sha256_crypt
from pydantic import BaseModel

from danswer.auth.schemas import UserRole
from danswer.configs.app_configs import API_KEY_HASH_ROUNDS


_API_KEY_HEADER_NAME = "Authorization"
# NOTE for others who are curious: In the context of a header, "X-" often refers
# to non-standard, experimental, or custom headers in HTTP or other protocols. It
# indicates that the header is not part of the official standards defined by
# organizations like the Internet Engineering Task Force (IETF).
_API_KEY_HEADER_ALTERNATIVE_NAME = "X-Danswer-Authorization"
_BEARER_PREFIX = "Bearer "
_API_KEY_PREFIX = "dn_"
_API_KEY_LEN = 192


class ApiKeyDescriptor(BaseModel):
    api_key_id: int
    api_key_display: str
    api_key: str | None = None  # only present on initial creation
    api_key_name: str | None = None
    api_key_role: UserRole

    user_id: uuid.UUID


def generate_api_key(tenant_id: str | None = None) -> str:
    # For backwards compatibility, if no tenant_id, generate old style key
    if not tenant_id:
        return _API_KEY_PREFIX + secrets.token_urlsafe(_API_KEY_LEN)

    encoded_tenant = quote(tenant_id)  # URL encode the tenant ID
    return f"{_API_KEY_PREFIX}{encoded_tenant}.{secrets.token_urlsafe(_API_KEY_LEN)}"


def extract_tenant_from_api_key_header(request: Request) -> str | None:
    """Extract tenant ID from request. Returns None if auth is disabled or invalid format."""
    raw_api_key_header = request.headers.get(
        _API_KEY_HEADER_ALTERNATIVE_NAME
    ) or request.headers.get(_API_KEY_HEADER_NAME)

    if not raw_api_key_header or not raw_api_key_header.startswith(_BEARER_PREFIX):
        return None

    api_key = raw_api_key_header[len(_BEARER_PREFIX) :].strip()

    if not api_key.startswith(_API_KEY_PREFIX):
        return None

    parts = api_key[len(_API_KEY_PREFIX) :].split(".", 1)
    if len(parts) != 2:
        return None

    tenant_id = parts[0]
    return unquote(tenant_id) if tenant_id else None


def hash_api_key(api_key: str) -> str:
    # NOTE: no salt is needed, as the API key is randomly generated
    # and overlaps are impossible
    return sha256_crypt.hash(api_key, salt="", rounds=API_KEY_HASH_ROUNDS)


def build_displayable_api_key(api_key: str) -> str:
    if api_key.startswith(_API_KEY_PREFIX):
        api_key = api_key[len(_API_KEY_PREFIX) :]

    return _API_KEY_PREFIX + api_key[:4] + "********" + api_key[-4:]


def get_hashed_api_key_from_request(request: Request) -> str | None:
    raw_api_key_header = request.headers.get(
        _API_KEY_HEADER_ALTERNATIVE_NAME
    ) or request.headers.get(_API_KEY_HEADER_NAME)
    if raw_api_key_header is None:
        return None

    if raw_api_key_header.startswith(_BEARER_PREFIX):
        raw_api_key_header = raw_api_key_header[len(_BEARER_PREFIX) :].strip()

    return hash_api_key(raw_api_key_header)
