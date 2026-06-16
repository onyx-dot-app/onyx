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
import onyx.server.features.build.external_apps.api as api
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_built_in_external_app
from onyx.db.external_app import get_policies
from onyx.db.models import ExternalApp
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.registry import action_policy_views
from onyx.external_apps.providers.registry import fetch_onyx_managed_built_in_apps
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
)
from onyx.server.features.build.external_apps.models import UpdateExternalAppRequest
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


@pytest.fixture(autouse=True)
def _enable_auto_provision(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provisioning defaults off; this module exercises it, so enable it. The
    disabled-path test flips it back to False."""
    monkeypatch.setattr(prov, "AUTO_PROVISION_DEFAULT_EXTERNAL_APPS", True)


def _set_managed_creds(
    monkeypatch: pytest.MonkeyPatch,
    creds: dict[ExternalAppType, dict[str, str]],
) -> None:
    """Set each managed provider's ``managed_org_credentials`` to the given
    values (or empty when unmentioned), mirroring how operator config flows in."""
    for app_type, provider in PROVIDERS.items():
        if not isinstance(provider, OnyxManagedExtApp):
            continue
        monkeypatch.setattr(
            provider, "managed_org_credentials", creds.get(app_type, {})
        )


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
# Provisioning / reconcile
# ---------------------------------------------------------------------------


def test_all_built_ins_are_onyx_managed() -> None:
    """Every built-in skill id has a registered provider, and all are currently
    Onyx-managed (seeded per tenant). When a future built-in opts out (not an
    ``OnyxManagedExtApp``, e.g. admins supply their own OAuth app), update this
    deliberately."""
    built_in = set(EXTERNAL_APP_BUILT_IN_SKILL_IDS)
    assert set(PROVIDERS) == built_in  # provider registry ↔ built-in skill ids
    assert set(_MANAGED_APP_TYPES) == built_in


def test_provisions_all_built_ins_disabled_with_credentials(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})

    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    for app_type in _MANAGED_APP_TYPES:
        app = get_built_in_external_app(db_session, app_type)
        assert app is not None, f"{app_type} not provisioned"
        assert app.skill.enabled is False

    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    assert gmail.organization_credentials.get_value(apply_mask=False) == _GMAIL_CREDS

    # An app with no configured creds is still provisioned, with empty creds.
    # Override-storage seeds no policy rows; defaults resolve at read time, so
    # the effective view still exposes the full catalog at its default policies.
    slack = get_built_in_external_app(db_session, ExternalAppType.SLACK)
    assert slack is not None
    assert slack.organization_credentials.get_value(apply_mask=False) == {}
    assert slack.policies == []
    views = action_policy_views(
        ExternalAppType.SLACK, get_policies(db_session, slack.id)
    )
    assert {v.action_id: v.state for v in views} == {
        endpoint.id: endpoint.default_policy
        for endpoint in get_endpoint_catalog(ExternalAppType.SLACK)
    }


def test_provisioning_skipped_when_auto_provision_disabled(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    monkeypatch.setattr(prov, "AUTO_PROVISION_DEFAULT_EXTERNAL_APPS", False)

    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    for app_type in _MANAGED_APP_TYPES:
        assert get_built_in_external_app(db_session, app_type) is None


def test_reconcile_is_idempotent_rotates_and_preserves_enabled(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(
        monkeypatch,
        {ExternalAppType.GMAIL: {"client_id": "id1", "client_secret": "v1"}},
    )
    prov.provision_built_in_external_apps(db_session)

    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    gmail.skill.enabled = True
    db_session.commit()

    # Re-run with rotated credentials.
    _set_managed_creds(
        monkeypatch,
        {ExternalAppType.GMAIL: {"client_id": "id2", "client_secret": "v2"}},
    )
    prov.provision_built_in_external_apps(db_session)
    db_session.expire_all()

    # Enabled state survives the reconcile; credentials are rotated in place.
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    assert gmail.skill.enabled is True
    assert gmail.organization_credentials.get_value(apply_mask=False) == {
        "client_id": "id2",
        "client_secret": "v2",
    }

    rows = list(
        db_session.scalars(
            select(ExternalApp).where(ExternalApp.app_type == ExternalAppType.GMAIL)
        ).all()
    )
    assert len(rows) == 1  # no duplicate row created


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

    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
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
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    prov.provision_built_in_external_apps(db_session)
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None
    app_id = gmail.id
    provisioned_patterns = list(gmail.upstream_url_patterns)

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
    assert list(gmail.upstream_url_patterns) == provisioned_patterns


def test_cloud_blocks_built_in_delete(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_managed_creds(monkeypatch, {})
    prov.provision_built_in_external_apps(db_session)
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
    _set_managed_creds(monkeypatch, {ExternalAppType.GMAIL: _GMAIL_CREDS})
    prov.provision_built_in_external_apps(db_session)
    gmail = get_built_in_external_app(db_session, ExternalAppType.GMAIL)
    assert gmail is not None

    monkeypatch.setattr(api, "MULTI_TENANT", False)
    resp = api._to_admin_response(gmail)

    assert resp.upstream_url_patterns  # config visible
    # Creds are present but masked — not the same raw values, not blanked away.
    assert resp.organization_credentials != {}
    assert resp.organization_credentials != _GMAIL_CREDS
