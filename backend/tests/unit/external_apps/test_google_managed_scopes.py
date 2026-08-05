"""The scope split between Onyx's own (Google-verified) OAuth client and a
deployment's own client: the managed grant stays clear of Google's restricted
scopes, and the catalog it exposes never outruns it."""

from __future__ import annotations

import pytest

from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers import registry
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.gmail import GmailAction
from onyx.external_apps.providers.google_drive import GoogleDriveAction
from onyx.external_apps.providers.registry import PROVIDERS, get_endpoint_catalog

# Requesting any of these subjects the OAuth client to an annual third-party
# security assessment: https://support.google.com/cloud/answer/13464325
_RESTRICTED_SCOPES = {
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.insert",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.settings.sharing",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.activity",
    "https://www.googleapis.com/auth/drive.activity.readonly",
    "https://www.googleapis.com/auth/drive.meet.readonly",
    "https://www.googleapis.com/auth/drive.metadata",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.scripts",
    # Legacy Drive-wide alias, still restricted.
    "https://www.googleapis.com/auth/docs",
}

_GOOGLE_APP_TYPES = [
    ExternalAppType.GMAIL,
    ExternalAppType.GOOGLE_DRIVE,
    ExternalAppType.GOOGLE_CALENDAR,
]


@pytest.fixture
def onyx_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend this deployment is managed cloud, where Onyx owns the client."""
    monkeypatch.setattr(registry, "MULTI_TENANT", True)


def _oauth(app_type: ExternalAppType) -> OAuthExternalAppProvider:
    provider = PROVIDERS[app_type]
    assert isinstance(provider, OAuthExternalAppProvider)
    return provider


@pytest.mark.parametrize("app_type", _GOOGLE_APP_TYPES)
def test_managed_scope_avoids_restricted_scopes(app_type: ExternalAppType) -> None:
    managed = _oauth(app_type).spec.oauth.managed_scope
    assert managed, f"{app_type} must declare a managed scope"
    assert not (set(managed.split()) & _RESTRICTED_SCOPES)


@pytest.mark.parametrize("app_type", _GOOGLE_APP_TYPES)
def test_scope_selection_follows_the_client(app_type: ExternalAppType) -> None:
    oauth = _oauth(app_type).spec.oauth
    assert oauth.scope_for(onyx_oauth_client=True) == oauth.managed_scope
    assert oauth.scope_for(onyx_oauth_client=False) == oauth.scope


@pytest.mark.parametrize("app_type", _GOOGLE_APP_TYPES)
def test_self_hosted_keeps_the_full_catalog(app_type: ExternalAppType) -> None:
    """Without Onyx's client nothing is filtered — self-hosted deployments run
    their own OAuth client and keep every action."""
    assert not registry.uses_onyx_oauth_client(app_type)
    assert get_endpoint_catalog(app_type) == PROVIDERS[app_type].spec.endpoint_catalog


@pytest.mark.usefixtures("onyx_client")
def test_gmail_is_send_only_on_onyx_client() -> None:
    assert [e.id for e in get_endpoint_catalog(ExternalAppType.GMAIL)] == [
        GmailAction.MESSAGES_SEND
    ]


@pytest.mark.usefixtures("onyx_client")
def test_drive_drops_only_shared_drive_listing_on_onyx_client() -> None:
    """`drive.file` + the Docs API cover the rest of the catalog; only
    drives.list needs a Drive-wide scope."""
    withheld = {
        e.id for e in PROVIDERS[ExternalAppType.GOOGLE_DRIVE].spec.endpoint_catalog
    } - {e.id for e in get_endpoint_catalog(ExternalAppType.GOOGLE_DRIVE)}
    assert withheld == {GoogleDriveAction.DRIVES_READ}


@pytest.mark.usefixtures("onyx_client")
def test_calendar_catalog_survives_on_onyx_client() -> None:
    """No Calendar scope is restricted, so the narrowed grant costs no actions."""
    assert (
        get_endpoint_catalog(ExternalAppType.GOOGLE_CALENDAR)
        == PROVIDERS[ExternalAppType.GOOGLE_CALENDAR].spec.endpoint_catalog
    )
