"""The cloud/self-hosted scope split for the Google providers: the cloud scope
stays clear of Google's restricted tier, and the catalog it exposes never
outruns it."""

from __future__ import annotations

import pytest

from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers import gmail, google_calendar, google_drive, registry
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
_CLOUD_SCOPES = [
    gmail._CLOUD_SCOPE,
    google_drive._CLOUD_SCOPE,
    google_calendar._CLOUD_SCOPE,
]


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend this deployment is cloud, where Onyx owns the OAuth client. Only
    the catalog reads this — ``spec.oauth.scope`` is resolved at import."""
    monkeypatch.setattr(registry, "MULTI_TENANT", True)


@pytest.mark.parametrize("cloud_scope", _CLOUD_SCOPES)
def test_cloud_scope_avoids_restricted_scopes(cloud_scope: str) -> None:
    assert not (set(cloud_scope.split()) & _RESTRICTED_SCOPES)


@pytest.mark.parametrize("app_type", _GOOGLE_APP_TYPES)
def test_self_hosted_keeps_the_full_catalog(app_type: ExternalAppType) -> None:
    assert not registry.uses_cloud_scope(app_type)
    assert get_endpoint_catalog(app_type) == PROVIDERS[app_type].spec.endpoint_catalog


@pytest.mark.usefixtures("cloud")
def test_gmail_cloud_catalog_is_send_and_draft_create() -> None:
    """`gmail.send` covers sending; the granular `gmail.drafts.create` scope
    covers draft creation. Everything else needs a restricted scope."""
    assert [e.id for e in get_endpoint_catalog(ExternalAppType.GMAIL)] == [
        GmailAction.MESSAGES_SEND,
        GmailAction.DRAFTS_CREATE,
    ]


@pytest.mark.usefixtures("cloud")
def test_drive_drops_only_shared_drive_listing_on_cloud() -> None:
    """`drive.file` + the Docs/Sheets/Slides APIs cover the rest of the
    catalog; only drives.list needs a Drive-wide scope."""
    withheld = {
        e.id for e in PROVIDERS[ExternalAppType.GOOGLE_DRIVE].spec.endpoint_catalog
    } - {e.id for e in get_endpoint_catalog(ExternalAppType.GOOGLE_DRIVE)}
    assert withheld == {GoogleDriveAction.DRIVES_READ}


@pytest.mark.usefixtures("cloud")
def test_calendar_catalog_survives_on_cloud() -> None:
    """No Calendar scope is restricted, so the narrowed scope costs no actions."""
    assert (
        get_endpoint_catalog(ExternalAppType.GOOGLE_CALENDAR)
        == PROVIDERS[ExternalAppType.GOOGLE_CALENDAR].spec.endpoint_catalog
    )
