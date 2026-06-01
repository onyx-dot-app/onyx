"""Render dynamic skill templates for the per-user skills fileset."""

from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import DocumentSourceDescription
from onyx.db.connector import _INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_policies
from onyx.db.models import ExternalApp
from onyx.db.models import User
from onyx.external_apps.providers.registry import action_policy_views
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


def build_action_availability_section(
    app_type: ExternalAppType,
    stored: dict[str, EndpointPolicy],
) -> str:
    """Render the warning listing the app's ``DENY`` (unavailable) actions, or an
    empty string when nothing is disabled. Available actions are intentionally
    omitted — the skill body already documents what the agent can do; this only
    fences off what it must not attempt.

    ``stored`` is the app's per-action overrides; an empty map falls back to the
    catalog defaults.
    """
    disabled = [
        f"- {view.normalised_name}"
        for view in action_policy_views(app_type, stored)
        if view.state == EndpointPolicy.DENY
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
) -> str:
    """Render an external-app SKILL.md with its per-user action availability.

    ``skill_dir`` is the skill's on-disk directory (holds ``SKILL.md.template``).
    """
    template = (skill_dir / "SKILL.md.template").read_text()
    stored = get_policies(db_session, external_app.id) if external_app else {}
    section = build_action_availability_section(app_type, stored)
    if section:
        return template.replace(ACTION_AVAILABILITY_PLACEHOLDER, section)
    # Nothing disabled: drop the placeholder and its trailing blank line so the
    # surrounding sections stay flush.
    return template.replace(f"{ACTION_AVAILABILITY_PLACEHOLDER}\n\n", "")
