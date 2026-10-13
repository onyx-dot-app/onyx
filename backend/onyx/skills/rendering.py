"""Render dynamic skill templates for the per-user skills fileset."""

import re
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, DocumentSourceDescription
from onyx.db.connector import _INTERNAL_ONLY_SOURCES
from onyx.db.connector_credential_pair import (
    CCPairAccessLevel,
    get_connector_credential_pairs_for_user,
)
from onyx.db.enums import EndpointPolicy, ExternalAppType, GatedAppKind
from onyx.db.external_app import get_external_app_by_skill_id
from onyx.db.gated_app import get_action_policies
from onyx.db.models import ExternalApp, Skill, User
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.registry import (
    action_policy_views,
    skill_template_values_for,
    uses_cloud_scope,
    withheld_on_cloud,
)
from onyx.skills.bundle import SKILL_MD_NAME, TEMPLATE_SUFFIX
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SKILL_TEMPLATE_NAME = f"{SKILL_MD_NAME}{TEMPLATE_SUFFIX}"

ACTION_AVAILABILITY_PLACEHOLDER = "{{ACTION_AVAILABILITY_SECTION}}"

# ``{{APP:<key>}}`` carries a value the provider resolved from the app's own
# configuration. An unknown key renders as ``_UNCONFIGURED_VALUE`` so a
# half-configured app says so rather than failing the push.
_APP_VALUE_RE = re.compile(r"\{\{APP:([A-Za-z0-9_]+)\}\}")
_UNCONFIGURED_VALUE = "(not configured — ask an admin to finish setting up this app)"

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
        access_level=CCPairAccessLevel.READ,
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


def substitute_app_values(template: str, values: Mapping[str, str]) -> str:
    """Fill ``{{APP:<key>}}`` from ``values``; an unknown or blank key renders
    as ``_UNCONFIGURED_VALUE`` so a half-configured app says so."""
    return _APP_VALUE_RE.sub(
        lambda match: values.get(match.group(1)) or _UNCONFIGURED_VALUE, template
    )


def render_external_app_skill(
    template: str,
    app_type: ExternalAppType,
    stored: dict[str, EndpointPolicy],
    app_values: Mapping[str, str] | None = None,
) -> str:
    """Pure template rendering for an external-app SKILL.md: apply the cloud
    description override, resolve the cloud-scope blocks, substitute the
    provider's ``{{APP:<key>}}`` values, then fill the action-availability
    placeholder."""
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
    template = substitute_app_values(template, app_values or {})
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


def app_template_values(external_app: ExternalApp | None) -> dict[str, str]:
    """The provider's ``{{APP:<key>}}`` values for this app row, or ``{}`` when
    there is no row or its config no longer resolves — rendering is a read-only
    projection, so a rejected config leaves placeholders unconfigured."""
    if external_app is None:
        return {}
    try:
        return skill_template_values_for(
            external_app.app_type,
            external_app.organization_credentials.get_value(apply_mask=False),
        )
    except OnyxError:
        logger.warning(
            "Could not resolve app config for external_app %s; rendering its "
            "skill with unconfigured placeholders",
            external_app.id,
        )
        return {}


def render_external_app_files(
    db_session: Session,
    skill: Skill,
    app_type: ExternalAppType,
    source_dir: Path,
) -> dict[str, str]:
    """Every rendered file for an external-app built-in, keyed by its path in
    the sandbox: ``SKILL.md`` plus any other ``*.template`` sibling, which is
    how a bundled helper gets the connected account baked in rather than taking
    it as an argument it could only ever be given one value for."""
    external_app = get_external_app_by_skill_id(db_session, skill.id)
    stored = (
        get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, external_app.id)
        if external_app
        else {}
    )
    values = app_template_values(external_app)
    rendered = {
        SKILL_MD_NAME: render_external_app_skill(
            (source_dir / _SKILL_TEMPLATE_NAME).read_text(), app_type, stored, values
        )
    }
    for path in sorted(source_dir.rglob(f"*{TEMPLATE_SUFFIX}")):
        if path.name == _SKILL_TEMPLATE_NAME:
            continue
        name = path.relative_to(source_dir).with_suffix("").as_posix()
        rendered[name] = substitute_app_values(path.read_text(), values)
    return rendered


def render_external_app_skill_for(
    db_session: Session,
    skill: Skill,
    app_type: ExternalAppType,
    source_dir: Path,
) -> str:
    """``skill``'s SKILL.md as the sandbox will see it. Shared by the push and
    the library preview, so a user previews what the agent reads."""
    return render_external_app_files(db_session, skill, app_type, source_dir)[
        SKILL_MD_NAME
    ]
