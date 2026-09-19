"""Render dynamic skill templates for the per-user skills fileset."""

import re
from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, DocumentSourceDescription
from onyx.db.connector import _INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.db.models import User
from onyx.external_apps.providers.registry import (
    action_policy_views,
    uses_cloud_scope,
    withheld_on_cloud,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

ACTION_AVAILABILITY_PLACEHOLDER = "{{ACTION_AVAILABILITY_SECTION}}"

# ``{{#IF_CLOUD_SCOPE}}`` blocks render only on cloud (``uses_cloud_scope``);
# ``{{^IF_CLOUD_SCOPE}}`` (mustache-style inverted) only elsewhere. Markers
# sit on their own lines; blocks cannot nest.
_CLOUD_SCOPE_BLOCK_RE = re.compile(
    r"\{\{([#^])IF_CLOUD_SCOPE\}\}\n(.*?)\{\{/IF_CLOUD_SCOPE\}\}\n", re.DOTALL
)

# On cloud, `cloud-description:` replaces the frontmatter `description:` that
# skill discovery reads. Pre-render it is ordinary extra frontmatter
# (SkillMetadata is extra="allow"); the rendered SKILL.md never carries it.
_CLOUD_DESCRIPTION_RE = re.compile(
    r"^cloud-description:[ \t]*(\S[^\n]*)\n", re.MULTILINE
)
_DESCRIPTION_RE = re.compile(r"^description:[^\n]*\n", re.MULTILINE)


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
    """The warning listing the app's unavailable actions — cloud-withheld plus
    the ``DENY`` entries from ``stored`` (the admin's per-action overrides) —
    or "" when none apply. Available actions are omitted: the skill body
    already documents those."""
    # Cloud-withheld actions never reach the filtered catalog, so the DENY
    # loop below can't see them.
    unavailable: list[str] = [
        endpoint.normalised_name for endpoint in withheld_on_cloud(app_type)
    ]
    unavailable.extend(
        view.normalised_name
        for view in action_policy_views(app_type, stored)
        if view.state == EndpointPolicy.DENY
    )
    if not unavailable:
        return ""
    header = "These actions are unavailable and should not be attempted:"
    return "\n".join([header, "", *(f"- {name}" for name in unavailable)])


def render_external_app_skill(
    template: str,
    app_type: ExternalAppType,
    stored: dict[str, EndpointPolicy],
) -> str:
    """Pure template rendering for an external-app SKILL.md: apply the cloud
    description override, resolve the cloud-scope blocks, then fill the
    action-availability placeholder."""
    is_cloud = uses_cloud_scope(app_type)

    cloud_description = _CLOUD_DESCRIPTION_RE.search(template)
    if cloud_description:
        template = _CLOUD_DESCRIPTION_RE.sub("", template, count=1)
        if is_cloud:
            replacement = f"description: {cloud_description.group(1)}\n"
            template = _DESCRIPTION_RE.sub(lambda _: replacement, template, count=1)

    def _resolve_block(match: re.Match[str]) -> str:
        # Keep a block whose condition matches (markers stripped); drop the rest.
        keep = (match.group(1) == "#") == is_cloud
        return match.group(2) if keep else ""

    template = _CLOUD_SCOPE_BLOCK_RE.sub(_resolve_block, template)
    section = build_action_availability_section(app_type, stored)
    if section:
        rendered = template.replace(ACTION_AVAILABILITY_PLACEHOLDER, section)
    else:
        # Nothing disabled: drop the placeholder and its trailing blank line so
        # the surrounding sections stay flush.
        rendered = template.replace(f"{ACTION_AVAILABILITY_PLACEHOLDER}\n\n", "")
    if "{{" in rendered:
        # Fail loudly rather than ship unresolved markup to the agent.
        offending = next(line for line in rendered.splitlines() if "{{" in line)
        raise ValueError(f"Unresolved skill-template markup: {offending!r}")
    return rendered
