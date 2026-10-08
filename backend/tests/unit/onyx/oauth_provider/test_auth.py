from uuid import uuid4

import pytest
from starlette.requests import Request

from onyx.auth.schemas import AuthBackend
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.server.oauth_provider.api import _session_hash
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


def test_consent_binding_tracks_bearer_even_with_an_unrelated_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_configs, "AUTH_BACKEND", AuthBackend.REDIS)
    user = User(id=uuid4(), account_type=AccountType.STANDARD)
    fingerprints = []
    for token in ("first-session", "second-session"):
        request = Request(
            {
                "type": "http",
                "headers": [
                    (b"cookie", f"{FASTAPI_USERS_AUTH_COOKIE_NAME}=unrelated".encode()),
                    (b"authorization", f"Bearer {token}".encode()),
                ],
                "state": {
                    "usage_credential": UsageCredentialIdentity(
                        UsageCredentialType.SESSION
                    )
                },
            }
        )
        fingerprints.append(_session_hash(request, user))
    assert fingerprints[0] != fingerprints[1]
