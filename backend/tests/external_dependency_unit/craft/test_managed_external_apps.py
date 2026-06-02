"""Onyx-managed (cloud) built-in external apps: provisioning + cloud guards.

Covers ``provision_built_in_external_apps`` in ``ee.onyx.server.tenants.provisioning``
(per-tenant provisioning; idempotent re-run) and the cloud lockdown in
``external_apps_api`` (admins may only enable/disable
+ set policies on built-in apps; never create, edit credentials/config, or
delete them). See
``docs/craft/features/external-apps/cloud-managed-app-credentials.md``.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

import ee.onyx.server.tenants.provisioning as prov
import onyx.server.features.build.api.external_apps_api as api
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_external_app_by_app_type
from onyx.db.models import ExternalApp
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.registry import fetch_onyx_managed_built_in_apps
from onyx.server.features.build.api.models import UpsertExternalAppRequest
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS

_BUILT_IN_SLUGS = list(EXTERNAL_APP_BUILT_IN_SKILL_IDS.values())
_MANAGED_APP_TYPES = [d.app_type for d in fetch_onyx_managed_built_in_apps()]
_GMAIL_CREDS = {"client_id": "cid", "client_secret": "sec"}


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _cleanup(db_session: Session) -> None:
    # Deleting the built-in skill cascades to its external_app + credential rows.
    db_session.execute(delete(Skill).where(Skill.slug.in_(_BUILT_IN_SLUGS)))
    db_session.commit()


@pytest.fixture(autouse=True)
def _clean_built_ins(db_session: Session) -> Generator[None, None, None]:
    """Start and end each test with no built-in external apps, so provisioning
    behaviour is asserted from a known-empty slate regardless of other tests."""
    _cleanup(db_session)
    yield
    _cleanup(db_session)


def _set_managed_creds(
    monkeypatch: pytest.MonkeyPatch,
    creds: dict[ExternalAppType, dict[str, str]],
) -> None:
    monkeypatch.setattr(prov, "load_managed_external_app_credentials", lambda: creds)


def _request(
    *,
    app_id: int | None = None,
    name: str = "Gmail",
    description: str = "",
    enabled: bool = True,
    upstream_url_patterns: list[str] | None = None,
    auth_template: dict[str, Any] | None = None,
    organization_credentials: dict[str, str] | None = None,
) -> UpsertExternalAppRequest:
    """A GMAIL upsert request with sensible defaults for the cloud-guard tests."""
    return UpsertExternalAppRequest(
        id=app_id,
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
# Provisioning / reconcile
# ---------------------------------------------------------------------------


def test_all_currently_defined_built_ins_are_onyx_managed() -> None:
    """For now every built-in is Onyx-managed (seeded per tenant). When a future
    built-in opts out (``onyx_managed=False``), update this deliberately."""
    assert set(_MANAGED_APP_TYPES) == set(EXTERNAL_APP_BUILT_IN_SKILL_IDS)


def test_provisions_all_built_ins_disabled_with_credentials(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})

    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    # Every Onyx-managed built-in is provisioned, disabled.
    for app_type in _MANAGED_APP_TYPES:
        app = get_external_app_by_app_type(db_session, app_type)
        assert app is not None, f"{app_type} not provisioned"
        assert app.skill.enabled is False

    # Configured credentials land (decrypted) on the matching app.
    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    assert gmail.organization_credentials.get_value(apply_mask=False) == _GMAIL_CREDS

    # An app with no configured creds is still provisioned, with empty creds and
    # default action policies seeded.
    slack = get_external_app_by_app_type(db_session, ExternalAppType.SLACK)
    assert slack is not None
    assert slack.organization_credentials.get_value(apply_mask=False) == {}
    assert len(slack.policies) >= 1


def test_provisioning_skipped_when_auto_provision_disabled(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    monkeypatch.setattr(prov, "AUTO_PROVISION_DEFAULT_EXTERNAL_APPS", False)

    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    # The flag short-circuits provisioning: no built-in rows are created.
    for app_type in _MANAGED_APP_TYPES:
        assert get_external_app_by_app_type(db_session, app_type) is None


def test_reconcile_is_idempotent_rotates_and_preserves_enabled(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: {"client_id": "v1"}})
    prov.provision_built_in_external_apps(db_session)

    # Admin enables the app.
    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    gmail.skill.enabled = True
    db_session.commit()

    # Re-run with rotated credentials.
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: {"client_id": "v2"}})
    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    # Enabled state survives the reconcile; credentials are rotated in place.
    assert gmail.skill.enabled is True
    assert gmail.organization_credentials.get_value(apply_mask=False) == {
        "client_id": "v2"
    }

    # No duplicate row was created.
    rows = list(
        db_session.scalars(
            select(ExternalApp).where(ExternalApp.app_type == ExternalAppType.GMAIL)
        ).all()
    )
    assert len(rows) == 1


def test_reconcile_does_not_wipe_creds_when_config_absent(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    prov.provision_built_in_external_apps(db_session)

    # Config no longer mentions gmail: reconcile must leave stored creds intact.
    _set_managed_creds(monkeypatch, {})
    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    assert gmail.organization_credentials.get_value(apply_mask=False) == _GMAIL_CREDS


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
        api.upsert_external_app(
            request=_request(app_id=None),
            _=test_user,
            db_session=db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    # Nothing was created.
    assert get_external_app_by_app_type(db_session, ExternalAppType.GMAIL) is None


def test_cloud_update_built_in_toggles_and_protects_creds_and_config(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    prov.provision_built_in_external_apps(db_session)
    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    app_id = gmail.id
    provisioned_patterns = list(gmail.upstream_url_patterns)

    monkeypatch.setattr(api, "MULTI_TENANT", True)
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)

    # Admin enables the app but also tries to overwrite credentials + config.
    resp = api.upsert_external_app(
        request=_request(
            app_id=app_id,
            name="Tampered",
            description="tampered",
            enabled=True,
            upstream_url_patterns=["https://evil.example.com/*"],
            auth_template={"X-Evil": "{client_secret}"},
            organization_credentials={"client_secret": "attacker"},
        ),
        _=test_user,
        db_session=db_session,
    )

    # The response never surfaces credentials or gateway config for a managed app.
    assert resp.organization_credentials == {}
    assert resp.auth_template == {}
    assert resp.upstream_url_patterns == []
    assert resp.enabled is True

    # Stored state: enablement flipped; credentials + config untouched.
    db_session.expire_all()
    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    assert gmail.skill.enabled is True
    assert gmail.organization_credentials.get_value(apply_mask=False) == _GMAIL_CREDS
    assert list(gmail.upstream_url_patterns) == provisioned_patterns
    assert "X-Evil" not in gmail.auth_template


def test_cloud_blocks_built_in_delete(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {})
    prov.provision_built_in_external_apps(db_session)
    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
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
    # Still present.
    assert get_external_app_by_app_type(db_session, ExternalAppType.GMAIL) is not None


def test_self_hosted_built_in_response_shows_config_and_masked_creds(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off cloud, a built-in app is admin-owned: config is visible and creds are
    masked (not blanked). This pins the managed-vs-not distinction in
    ``_to_admin_response``."""
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    prov.provision_built_in_external_apps(db_session)
    gmail = get_external_app_by_app_type(db_session, ExternalAppType.GMAIL)
    assert gmail is not None

    monkeypatch.setattr(api, "MULTI_TENANT", False)
    resp = api._to_admin_response(gmail)

    assert resp.upstream_url_patterns  # config visible
    # Creds are present but masked — not the same raw values, not blanked away.
    assert resp.organization_credentials != {}
    assert resp.organization_credentials != _GMAIL_CREDS
