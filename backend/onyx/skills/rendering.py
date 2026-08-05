"""Render dynamic skill templates for the per-user skills fileset."""

from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, DocumentSourceDescription
from onyx.db.connector import _INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.enums import EndpointPolicy, ExternalAppType, GatedAppKind
from onyx.db.gated_app import get_action_policies
from onyx.db.models import ExternalApp, User
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
    """Render the list of actions the agent can actually perform: the catalog the
    app's OAuth grant authorizes, minus anything an admin set to ``DENY``.

    An allow-list rather than a deny-list, so the agent plans against what it
    has. The skill body documents the provider's full surface, which can outrun
    the grant — a narrower OAuth client (see ``get_endpoint_catalog``) leaves
    documented commands unauthorized, and enumerating those instead would mean
    listing everything the agent *can't* do.

    ``stored`` is the app's per-action overrides; an empty map falls back to the
    catalog defaults.
    """
    available = [
        view
        for view in action_policy_views(app_type, stored)
        if view.state != EndpointPolicy.DENY
    ]
    if not available:
        return "No actions are available for this app — do not use this skill."
    header = "Only these actions are available; anything else will be rejected:"
    return "\n".join(
        [
            header,
            "",
            *(f"- {view.normalised_name} — {view.description}" for view in available),
        ]
    )


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
    stored = (
        get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, external_app.id)
        if external_app
        else {}
    )
    return template.replace(
        ACTION_AVAILABILITY_PLACEHOLDER,
        build_action_availability_section(app_type, stored),
    )
