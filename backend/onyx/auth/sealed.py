"""Draft credentials, sealed for the trip through the browser.

A draft credential is a new account that is not saved until its connector is
created. Wherever it must leave the server (an OAuth callback's result, a check
task's message), it travels as a sealed string: AES-GCM ciphertext that only
this deployment can open, bound to the user who made it and to an expiry. The
browser holds the string but cannot read or change it. Nothing is stored.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, ValidationError

from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.constants import DocumentSource
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.contextvars import get_current_tenant_id

# Names this use of the secret, so the derived key serves nothing else.
_CONTEXT = b"onyx-draft-credential-v1"
_NONCE_BYTES = 12

# How long a draft stays usable: about an OAuth access token's lifetime.
DRAFT_CREDENTIAL_TTL = timedelta(hours=1)


def _derive_key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_CONTEXT).derive(
        secret.encode()
    )


# USER_AUTH_SECRET is required on a real deployment (see
# `verify_user_auth_secret`), and the API server and the workers share it.
_KEY = _derive_key(USER_AUTH_SECRET)


class DraftCredential(BaseModel):
    """What a sealed draft carries."""

    user_id: UUID
    tenant_id: str
    source: DocumentSource
    credential_json: dict[str, Any]
    expires_at: datetime


def seal_draft_credential(
    credential_json: dict[str, Any],
    *,
    user_id: UUID,
    source: DocumentSource,
    ttl: timedelta = DRAFT_CREDENTIAL_TTL,
) -> str:
    """Seals a draft credential for `user_id` in the current tenant, usable
    until `ttl` from now."""
    draft = DraftCredential(
        user_id=user_id,
        tenant_id=get_current_tenant_id(),
        source=source,
        credential_json=credential_json,
        expires_at=datetime.now(timezone.utc) + ttl,
    )
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_KEY).encrypt(nonce, draft.model_dump_json().encode(), _CONTEXT)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def unseal_draft_credential(sealed: str, *, user_id: UUID) -> DraftCredential:
    """Opens a sealed draft credential.

    Raises:
        OnyxError: INVALID_INPUT when the string is malformed, was changed,
            was sealed with another key or belongs to another user or
            tenant;
            CREDENTIAL_EXPIRED when it is past its expiry.
    """
    try:
        raw = base64.urlsafe_b64decode(sealed.encode())
        plaintext = AESGCM(_KEY).decrypt(
            raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], _CONTEXT
        )
        draft = DraftCredential.model_validate_json(plaintext)
    except (binascii.Error, ValueError, InvalidTag, ValidationError) as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "The draft credential is not valid."
        ) from e
    # A draft of another user or tenant reads as invalid, so it does not leak.
    if draft.user_id != user_id or draft.tenant_id != get_current_tenant_id():
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "The draft credential is not valid."
        )
    if draft.expires_at <= datetime.now(timezone.utc):
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_EXPIRED,
            "The draft credential expired. Sign in again.",
        )
    return draft


def draft_credential_digest(draft: DraftCredential) -> str:
    """A stable name for a draft's values, e.g. for a cache key. Keyed, so a
    guessable secret cannot be recovered from it."""
    material = json.dumps(
        {
            "user_id": str(draft.user_id),
            "tenant_id": draft.tenant_id,
            "source": draft.source.value,
            "credential_json": draft.credential_json,
        },
        sort_keys=True,
        default=str,
    )
    return hmac.new(_KEY, material.encode(), hashlib.sha256).hexdigest()
