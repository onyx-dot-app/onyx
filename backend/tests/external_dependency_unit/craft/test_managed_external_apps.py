"""Onyx-managed (cloud) built-in external apps: registry invariants + cloud guards.

Covers the cloud lockdown in ``external_apps_api`` (admins may only
enable/disable + set policies on built-in apps; never create, edit
credentials/config, or delete them). See
``docs/craft/features/external-apps/cloud-managed-app-credentials.md``.

Built-in apps are seeded into existing tenants by an Alembic migration rather
than at tenant setup, so these tests seed directly via ``create_external_app``.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import onyx.server.features.build.external_apps.api as api
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import create_external_app
from onyx.db.external_app import get_built_in_external_app
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.registry import fetch_onyx_managed_built_in_apps
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
)
from onyx.server.features.build.external_apps.models import UpdateExternalAppRequest
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS

_BUILT_IN_SLUGS = list(EXTERNAL_APP_BUILT_IN_SKILL_IDS.values())
_MANAGED_APP_TYPES = [d.app_type for d in fetch_onyx_managed_built_in_apps()]
_GMAIL_CREDS = {"client_id": "cid", "client_secret": "sec"}
_GMAIL_PATTERNS = ["https://gmail\\.googleapis\\.com/gmail/.*"]


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _cleanup(db_session: Session) -> None:
    # Deleting the built-in skill cascades to its external_app + credential rows.
    db_session.execute(delete(Skill).where(Skill.slug.in_(_BUILT_IN_SLUGS)))
    db_session.commit()


@pytest.fixture(autouse=True)
def _clean_built_ins(db_session: Session) -> Generator[None, None, None]:
    """Start and end each test with no built-in external apps, so behaviour is
    asserted from a known-empty slate regardless of other tests."""
    _cleanup(db_session)
    yield
    _cleanup(db_session)


def _seed_built_in(
    db_session: Session,
    app_type: ExternalAppType,
    credentials: dict[str, str],
) -> None:
    """Directly seed a built-in external app (disabled), standing in for the
    migration that seeds these per tenant, so the cloud-guard tests have a
    managed app to act on."""
    create_external_app(
        db_session=db_session,
        name=app_type.value.title(),
        description="",
        bundle_file_id="",
        bundle_sha256="",
        app_type=app_type,
        upstream_url_patterns=list(_GMAIL_PATTERNS),
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials=credentials,
        enabled=False,
        is_public=True,
        action_policies=None,
    )
    db_session.commit()


def _create_request(
    *,
    name: str = "Gmail",
    description: str = "",
    enabled: bool = True,
    upstream_url_patterns: list[str] | None = None,
    auth_template: dict[str, Any] | None = None,
    organization_credentials: dict[str, str] | None = None,
) -> CreateBuiltInExternalAppRequest:
    """A GMAIL create request with sensible defaults for the cloud-guard tests."""
    return CreateBuiltInExternalAppRequest(
        name=name,
        description=description,
        enabled=enabled,
        app_type=ExternalAppType.GMAIL,
        upstream_url_patterns=upstream_url_patterns or [],
        auth_template=auth_template or {},
        organization_credentials=organization_credentials or {},
        action_policies=None,
    )


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------


def test_all_built_ins_are_onyx_managed() -> None:
    """Every built-in skill id has a registered provider, and all are currently
    Onyx-managed. When a future built-in opts out (not an ``OnyxManagedExtApp``,
    e.g. admins supply their own OAuth app), update this deliberately."""
    built_in = set(EXTERNAL_APP_BUILT_IN_SKILL_IDS)
    assert set(PROVIDERS) == built_in  # provider registry ↔ built-in skill ids
    assert set(_MANAGED_APP_TYPES) == built_in


# ---------------------------------------------------------------------------
# Cloud lockdown (admin API)
# ---------------------------------------------------------------------------


def test_cloud_blocks_built_in_create(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "MULTI_TENANT", True)
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)

    with pytest.raises(OnyxError) as exc:
        api.create_built_in_external_app(
            request=_create_request(),
            _=test_user,
            db_session=db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert get_built_in_external_app(db_session, ExternalAppType.GMAIL) is None


def test_cloud_patch_toggles_enablement_and_protects_creds_and_config(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PATCH path flips enablement for a managed built-in; credentials +
    gateway config are Onyx-owned and ignored even when the request carries them,
    and the response blanks them."""
    _seed_built_in(db_session, ExternalAppType.GMAIL, _GMAIL_CREDS)
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    app_id = gmail.id
    seeded_patterns = list(gmail.upstream_url_patterns)

    monkeypatch.setattr(api, "MULTI_TENANT", True)
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)

    # The request supplies config fields too; for a managed app they must be
    # silently ignored (Onyx-owned), with only enablement applied.
    resp = api.update_external_app_admin(
        external_app_id=app_id,
        request=UpdateExternalAppRequest(
            enabled=True,
            upstream_url_patterns=["https://evil.example.com/.*"],
            auth_template={"client_id": "attacker"},
            organization_credentials={"client_secret": "attacker"},
        ),
        _=test_user,
        db_session=db_session,
    )

    assert resp.organization_credentials == {}
    assert resp.auth_template == {}
    assert resp.upstream_url_patterns == []
    assert resp.enabled is True

    db_session.expire_all()
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    assert gmail.skill.enabled is True
    assert gmail.organization_credentials.get_value(apply_mask=False) == _GMAIL_CREDS
    assert list(gmail.upstream_url_patterns) == seeded_patterns


def test_cloud_blocks_built_in_delete(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_built_in(db_session, ExternalAppType.GMAIL, {})
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    app_id = gmail.id

    monkeypatch.setattr(api, "MULTI_TENANT", True)

    with pytest.raises(OnyxError) as exc:
        api.delete_external_app_admin(
            external_app_id=app_id,
            _=test_user,
            db_session=db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert get_built_in_external_app(db_session, ExternalAppType.GMAIL) is not None


def test_self_hosted_built_in_response_shows_config_and_masked_creds(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off cloud, a built-in app is admin-owned: config is visible and creds are
    masked (not blanked). This pins the managed-vs-not distinction in
    ``_to_admin_response``."""
    _seed_built_in(db_session, ExternalAppType.GMAIL, _GMAIL_CREDS)
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None

    monkeypatch.setattr(api, "MULTI_TENANT", False)
    resp = api._to_admin_response(gmail)

    assert resp.upstream_url_patterns  # config visible
    # Creds are present but masked — not the same raw values, not blanked away.
    assert resp.organization_credentials != {}
    assert resp.organization_credentials != _GMAIL_CREDS
