"""Render dynamic skill templates for the per-user skills fileset."""

from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, DocumentSourceDescription
from onyx.db.connector import _INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.enums import EndpointPolicy, ExternalAppType, GatedAppKind
from onyx.db.gated_app import get_action_policies
from onyx.db.models import ExternalApp, User
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.registry import effective_policy, get_endpoint_catalog
from onyx.utils.logger import setup_logger

logger = setup_logger()

ACTION_AVAILABILITY_PLACEHOLDER = "{{ACTION_AVAILABILITY_SECTION}}"


def build_available_sources_section(
    db_session: Session,
    user: User,
) -> str:
    """Build the available sources section for the company-search SKILL.md."""
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session,
        user,
        get_editable=False,
        eager_load_connector=True,
    )

    if not cc_pairs:
        return "No connected sources available for this user."

    seen: set[str] = set()
    for cc_pair in cc_pairs:
        source = cc_pair.connector.source
        if source in _INTERNAL_ONLY_SOURCES:
            continue
        source_value = (
            source.value if isinstance(source, DocumentSource) else str(source)
        )
        seen.add(source_value)

    if not seen:
        return "No connected sources available for this user."

    lines: list[str] = []
    for source_value in sorted(seen):
        try:
            source_enum = DocumentSource(source_value)
        except ValueError:
            source_enum = None
        fallback = source_value.replace("_", " ").title()
        description = (
            DocumentSourceDescription.get(source_enum, fallback)
            if source_enum
            else fallback
        )
        lines.append(f"- `{source_value}` — {description}")

    return "\n".join(lines)


def render_company_search_skill(
    db_session: Session,
    user: User,
    skills_dir: Path,
) -> str:
    """Render the company-search SKILL.md with the user's available sources.

    ``skills_dir`` is the parent directory of ``company-search/``.
    """
    template_path = skills_dir / "company-search" / "SKILL.md.template"
    template = template_path.read_text()
    sources_section = build_available_sources_section(db_session, user)
    return template.replace("{{AVAILABLE_SOURCES_SECTION}}", sources_section)


def _is_scope_denied(
    endpoint: EndpointSpec,
    granted_scopes: list[str] | None,
) -> bool:
    """Whether the user's OAuth grant can't authorize ``endpoint``.

    Only actions that declare ``required_scopes`` are gated — those are the ones
    a provider requests as *optional* scopes, so the grant genuinely differs per
    user (a read-only HubSpot account connects fine but can't write). Anything
    else is authorized by definition for a connected user.

    ``granted_scopes is None`` means "grant unknown" (a legacy credential row, or
    a provider that doesn't report scopes). Unknown is never treated as denied:
    hiding actions on a missing signal would silently break every pre-existing
    credential, so the DENY-policy behaviour is all that applies there.
    """
    if granted_scopes is None or not endpoint.required_scopes:
        return False
    return not set(endpoint.required_scopes).issubset(granted_scopes)


def build_action_availability_section(
    app_type: ExternalAppType,
    stored: dict[str, EndpointPolicy],
    granted_scopes: list[str] | None = None,
) -> str:
    """Render the warning listing the app's unavailable actions, or an empty
    string when nothing is unavailable. Available actions are intentionally
    omitted — the skill body already documents what the agent can do; this only
    fences off what it must not attempt.

    An action is unavailable when the admin set its policy to ``DENY``, or when
    the user's OAuth grant lacks a scope the action requires (see
    ``_is_scope_denied``) — advertising a write to a read-only account only gets
    the agent a 401 it then has to reason about. Both land in one list, so an
    action is never named twice.

    ``stored`` is the app's per-action overrides; an empty map falls back to the
    catalog defaults. ``granted_scopes`` is the user's persisted grant, or
    ``None`` when it's unknown (nothing is scope-gated then).
    """
    disabled = [
        f"- {endpoint.normalised_name}"
        for endpoint in get_endpoint_catalog(app_type)
        if effective_policy(endpoint, stored) == EndpointPolicy.DENY
        or _is_scope_denied(endpoint, granted_scopes)
    ]
    if not disabled:
        return ""
    header = "These actions are unavailable and should not be attempted:"
    return "\n".join([header, "", *disabled])


def render_external_app_skill(
    db_session: Session,
    app_type: ExternalAppType,
    external_app: ExternalApp | None,
    skill_dir: Path,
    granted_scopes: list[str] | None = None,
) -> str:
    """Render an external-app SKILL.md with its per-user action availability.

    ``skill_dir`` is the skill's on-disk directory (holds ``SKILL.md.template``).
    ``granted_scopes`` is the rendering user's persisted OAuth grant for the app;
    ``None`` (the default) means unknown, which gates nothing.
    """
    template = (skill_dir / "SKILL.md.template").read_text()
    stored = (
        get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, external_app.id)
        if external_app
        else {}
    )
    section = build_action_availability_section(app_type, stored, granted_scopes)
    if section:
        return template.replace(ACTION_AVAILABILITY_PLACEHOLDER, section)
    # Nothing disabled: drop the placeholder and its trailing blank line so the
    # surrounding sections stay flush.
    return template.replace(f"{ACTION_AVAILABILITY_PLACEHOLDER}\n\n", "")
