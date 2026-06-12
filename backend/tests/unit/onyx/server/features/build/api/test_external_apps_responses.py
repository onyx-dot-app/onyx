"""Unit tests for the credential_error flag on external-app API responses."""

from __future__ import annotations

import json
from typing import Any

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Skill
from onyx.server.features.build.api.external_apps_api import _to_admin_response
from onyx.server.features.build.api.external_apps_api import _to_user_response
from onyx.utils.sensitive import SensitiveValue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bad_sensitive() -> SensitiveValue[dict[str, Any]]:
    """SensitiveValue whose decryption raises UnicodeDecodeError (a ValueError subclass)."""
    return SensitiveValue(
        encrypted_bytes=b"\xa5garbage",
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


def _good_sensitive(data: dict[str, Any]) -> SensitiveValue[dict[str, Any]]:
    """SensitiveValue that decrypts successfully to ``data``."""
    raw = json.dumps(data).encode()
    return SensitiveValue(
        encrypted_bytes=raw,
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


def _make_app(
    org_creds: SensitiveValue[dict[str, Any]],
    auth_template: dict[str, Any],
    app_id: int = 1,
) -> ExternalApp:
    skill = Skill(name="Test App", description="desc", slug="test-app", enabled=True)
    app = ExternalApp(
        organization_credentials=org_creds,
        auth_template=auth_template,
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[],
    )
    app.__dict__["id"] = app_id
    app.skill = skill
    app.policies = []
    return app


def _make_user_cred(
    user_credentials: SensitiveValue[dict[str, Any]],
) -> ExternalAppUserCredential:
    return ExternalAppUserCredential(user_credentials=user_credentials)


# ---------------------------------------------------------------------------
# _to_user_response
# ---------------------------------------------------------------------------


def test_to_user_response_bad_user_creds_sets_credential_error() -> None:
    """Good org creds, bad user blob → credential_error True, not authenticated."""
    app = _make_app(
        org_creds=_good_sensitive({}),
        auth_template={"Authorization": "Bearer {token}"},
    )
    user_cred = _make_user_cred(_bad_sensitive())
    resp = _to_user_response(app, user_cred)
    assert resp.credential_error is True
    assert resp.authenticated is False


def test_to_user_response_good_creds_no_credential_error() -> None:
    """Good org creds, good user blob with required key → no error, authenticated."""
    app = _make_app(
        org_creds=_good_sensitive({}),
        auth_template={"Authorization": "Bearer {token}"},
    )
    user_cred = _make_user_cred(_good_sensitive({"token": "t"}))
    resp = _to_user_response(app, user_cred)
    assert resp.credential_error is False
    assert resp.authenticated is True


# ---------------------------------------------------------------------------
# _to_admin_response
# ---------------------------------------------------------------------------


def test_to_admin_response_bad_org_creds_sets_credential_error() -> None:
    """Bad org creds → credential_error True, organization_credentials empty."""
    app = _make_app(
        org_creds=_bad_sensitive(),
        auth_template={},
    )
    resp = _to_admin_response(app)
    assert resp.credential_error is True
    assert resp.organization_credentials == {}


def test_to_admin_response_good_org_creds_no_credential_error() -> None:
    """Good org creds → credential_error False, key present (value masked)."""
    app = _make_app(
        org_creds=_good_sensitive({"api_key": "k"}),
        auth_template={},
    )
    resp = _to_admin_response(app)
    assert resp.credential_error is False
    assert set(resp.organization_credentials) == {"api_key"}
