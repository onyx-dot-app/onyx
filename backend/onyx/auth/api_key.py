import hashlib
import secrets
import uuid
from urllib.parse import quote

from fastapi import Request
from passlib.hash import sha256_crypt
from pydantic import BaseModel

from onyx.auth.constants import API_KEY_LENGTH
from onyx.auth.constants import API_KEY_PREFIX
from onyx.auth.constants import DEPRECATED_API_KEY_PREFIX
from onyx.auth.schemas import UserRole
from onyx.auth.utils import get_hashed_bearer_token_from_request
from onyx.configs.app_configs import API_KEY_HASH_ROUNDS
from shared_configs.configs import MULTI_TENANT


class ApiKeyDescriptor(BaseModel):
    api_key_id: int
    api_key_display: str
    api_key: str | None = None  # only present on initial creation
    api_key_name: str | None = None
    api_key_role: UserRole

    user_id: uuid.UUID


def generate_api_key(tenant_id: str | None = None) -> str:
    if not MULTI_TENANT or not tenant_id:
        return API_KEY_PREFIX + secrets.token_urlsafe(API_KEY_LENGTH)

    encoded_tenant = quote(tenant_id)  # URL encode the tenant ID
    return f"{API_KEY_PREFIX}{encoded_tenant}.{secrets.token_urlsafe(API_KEY_LENGTH)}"


def _deprecated_hash_api_key(api_key: str) -> str:
    return sha256_crypt.hash(api_key, salt="", rounds=API_KEY_HASH_ROUNDS)


def hash_api_key(api_key: str) -> str:
    # NOTE: no salt is needed, as the API key is randomly generated
    # and overlaps are impossible
    if api_key.startswith(API_KEY_PREFIX):
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    if api_key.startswith(DEPRECATED_API_KEY_PREFIX):
        return _deprecated_hash_api_key(api_key)

    raise ValueError(f"Invalid API key prefix: {api_key[:3]}")


def build_displayable_api_key(api_key: str) -> str:
    if api_key.startswith(API_KEY_PREFIX):
        api_key = api_key[len(API_KEY_PREFIX) :]

    return API_KEY_PREFIX + api_key[:4] + "********" + api_key[-4:]


def get_hashed_api_key_from_request(request: Request) -> str | None:
    """Extract and hash API key from Authorization header.

    Accepts both "Bearer <key>" and raw key formats.
    """
    return get_hashed_bearer_token_from_request(
        request,
        valid_prefixes=[API_KEY_PREFIX, DEPRECATED_API_KEY_PREFIX],
        hash_fn=hash_api_key,
        allow_non_bearer=True,  # API keys historically support both formats
    )
