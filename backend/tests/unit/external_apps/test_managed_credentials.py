"""Each Onyx-managed provider resolves its Onyx-owned credentials from the
per-field ``managed_org_credentials`` values
(``OnyxManagedExtApp.configured_managed_credentials``)."""

from __future__ import annotations

import pytest

from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.registry import get_onyx_managed_provider
from onyx.external_apps.providers.registry import PROVIDERS


def _gmail() -> OnyxManagedExtApp:
    provider = get_onyx_managed_provider(ExternalAppType.GMAIL)
    assert provider is not None
    return provider


def test_managed_credential_keys_match_required_fields() -> None:
    """Each Onyx-managed provider maps exactly its required credential fields.
    (Also enforced at class-definition time in ExternalAppProvider.__init_subclass__;
    this pins it as an explicit, readable invariant.)"""
    managed = [p for p in PROVIDERS.values() if isinstance(p, OnyxManagedExtApp)]
    assert managed  # sanity: at least one managed provider exists
    for provider in managed:
        required = {
            f.key for f in provider.spec.descriptor.required_org_credential_fields
        }
        assert set(provider.managed_org_credentials) == required


def test_unset_is_none() -> None:
    # No EXT_APP_* secrets are set in the test env, so the constants are blank.
    assert _gmail().configured_managed_credentials() is None


def test_full_set_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _gmail(),
        "managed_org_credentials",
        {"client_id": "cid", "client_secret": "sec"},
    )

    assert _gmail().configured_managed_credentials() == {
        "client_id": "cid",
        "client_secret": "sec",
    }


def test_partial_set_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only one of GMAIL's two fields is set: unusable, so treated as unconfigured.
    monkeypatch.setattr(
        _gmail(), "managed_org_credentials", {"client_id": "cid", "client_secret": ""}
    )

    assert _gmail().configured_managed_credentials() is None


def test_blank_value_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _gmail(),
        "managed_org_credentials",
        {"client_id": "cid", "client_secret": "   "},
    )

    assert _gmail().configured_managed_credentials() is None
