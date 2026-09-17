"""The cloud/self-hosted scope split for the Google providers: the cloud scope
stays clear of Google's restricted tier, the catalog it exposes never outruns
it, and the SKILL.md rendered under it surfaces the withheld actions and
per-grant caveats."""

from __future__ import annotations

import pytest

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.external_apps.providers import gmail, google_calendar, google_drive, registry
from onyx.external_apps.providers.gmail import GmailAction
from onyx.external_apps.providers.google_drive import GoogleDriveAction
from onyx.external_apps.providers.registry import PROVIDERS, get_endpoint_catalog
from onyx.skills.built_in import BUILTIN_SKILLS_PATH
from onyx.skills.rendering import render_external_app_skill

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


# --- Skill-facing cloud-scope caveats ---
# The rendered SKILL.md must surface what the narrowed cloud grant changes:
# the {{#IF_CLOUD_SCOPE}} note carries the why/guidance, and the unavailable
# list carries the withheld actions (nothing else surfaces them — they are
# filtered out of the catalog).

_SKILL_TEMPLATES = {
    ExternalAppType.GOOGLE_DRIVE: "google-drive",
    ExternalAppType.GMAIL: "gmail",
}


def _render_skill(
    app_type: ExternalAppType,
    stored: dict[str, EndpointPolicy] | None = None,
) -> str:
    template = (
        BUILTIN_SKILLS_PATH / _SKILL_TEMPLATES[app_type] / "SKILL.md.template"
    ).read_text()
    return render_external_app_skill(template, app_type, stored or {})


@pytest.mark.usefixtures("cloud")
def test_drive_skill_warns_about_per_file_grant_on_cloud() -> None:
    rendered = _render_skill(ExternalAppType.GOOGLE_DRIVE)
    assert "drive.file" in rendered
    assert "get-doc" in rendered
    # DRIVES_READ is withheld on cloud; it must be listed, not silently absent.
    assert "- List shared drives" in rendered
    # Discovery must not promise Drive-wide search on cloud.
    assert "description: Create, upload, and organize" in rendered
    assert "cloud-description" not in rendered


@pytest.mark.usefixtures("cloud")
def test_gmail_skill_is_send_and_draft_create_on_cloud() -> None:
    rendered = _render_skill(ExternalAppType.GMAIL)
    assert "gmail.send" in rendered
    # Withheld actions are fenced off in the unavailable list...
    assert "- Read messages" in rendered
    assert "- Update a draft" in rendered
    # ...and their usage docs are not rendered at all.
    assert "### Send a message (write)" in rendered
    assert "### List / search messages" not in rendered
    assert "draft-update" not in rendered
    assert "### Download an attachment" not in rendered
    # Surviving actions are not fenced, and draft-create is documented.
    assert "- Send a message" not in rendered
    assert "- Create a draft" not in rendered
    assert "### Create a draft (write, not sent)" in rendered
    # Skill discovery reads the description: it must not advertise reads.
    assert "description: Send email and create drafts" in rendered
    assert "Read, search" not in rendered
    assert "cloud-description" not in rendered


def test_gmail_skill_documents_everything_self_hosted() -> None:
    rendered = _render_skill(ExternalAppType.GMAIL)
    assert "### List / search messages" in rendered
    assert "### Update a draft (write, not sent)" in rendered
    assert "### Download an attachment" in rendered
    assert "description: Read, search, send, and draft email" in rendered
    assert "cloud-description" not in rendered


@pytest.mark.usefixtures("cloud")
def test_cloud_note_precedes_the_unavailable_list_with_deny_merged() -> None:
    """An admin DENY must not displace the cloud note (or vice versa): the note
    renders first, and the unavailable list carries both the withheld action
    and the DENY override."""
    rendered = _render_skill(
        ExternalAppType.GOOGLE_DRIVE,
        {GoogleDriveAction.FILES_CREATE: EndpointPolicy.DENY},
    )
    assert rendered.index("drive.file") < rendered.index(
        "These actions are unavailable"
    )
    assert "- List shared drives" in rendered
    assert "- Create or upload a file" in rendered


@pytest.mark.parametrize(
    "app_type", [ExternalAppType.GOOGLE_DRIVE, ExternalAppType.GMAIL]
)
def test_self_hosted_skill_has_no_cloud_caveats(app_type: ExternalAppType) -> None:
    rendered = _render_skill(app_type)
    assert "drive.file" not in rendered
    assert "Create, upload, and organize" not in rendered
    assert "gmail.drafts.create" not in rendered
    assert "These actions are unavailable" not in rendered
