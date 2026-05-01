"""Shared utilities for generating AGENTS.md content.

This module provides functions for building dynamic agent instructions
that are shared between local and kubernetes sandbox managers.
"""

import threading
from pathlib import Path

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import DocumentSourceCraftDescription
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Cache for skills section (skills are static, cached indefinitely)
_skills_cache: dict[str, str] = {}
_skills_cache_lock = threading.Lock()

# Provider display name mapping
PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "azure": "Azure OpenAI",
    "google": "Google AI",
    "bedrock": "AWS Bedrock",
    "vertex": "Google Vertex AI",
}


def get_provider_display_name(provider: str | None) -> str | None:
    """Get user-friendly display name for LLM provider.

    Args:
        provider: Internal provider name

    Returns:
        User-friendly display name, or None if provider is None
    """
    if not provider:
        return None

    return PROVIDER_DISPLAY_NAMES.get(provider, provider.title())


def build_user_context(user_name: str | None, user_role: str | None) -> str:
    """Build the user context section for AGENTS.md.

    Args:
        user_name: User's name
        user_role: User's role/title

    Returns:
        Formatted user context string
    """
    if not user_name:
        return ""

    if user_role:
        return f"You are assisting **{user_name}**, {user_role}, with their work."
    return f"You are assisting **{user_name}** with their work."


# Content for the org_info section when demo data is enabled
ORG_INFO_SECTION_CONTENT = """## Organization Info

The `org_info/` directory contains information about the organization and user context:

- `AGENTS.md`: Description of available organizational information files
- `user_identity_profile.txt`: Contains the current user's name, email, and organization
  they work for. Use this information when personalizing outputs or when the user asks
  about their identity.
- `organization_structure.json`: Contains a JSON representation of the organization's
  groups, managers, and their direct reports. Use this to understand reporting
  relationships and team structures."""


# Content for the attachments section when user has uploaded files
ATTACHMENTS_SECTION_CONTENT = """## Attachments (PRIORITY)

The `attachments/` directory contains files that the user has explicitly
uploaded during this session. **These files are critically important** and
should be treated as high-priority context.

### Why Attachments Matter

- The user deliberately chose to upload these files, signaling they are directly relevant to the task
- These files often contain the specific data, requirements, or examples the user wants you to work with
- They may include spreadsheets, documents, images, or code that should inform your work

### Required Actions

**At the start of every task, you MUST:**

1. **Check for attachments**: List the contents of `attachments/` to see what the user has provided
2. **Read and analyze each file**: Thoroughly examine every attachment to understand its contents and relevance
3. **Reference attachment content**: Use the information from attachments to inform your responses and outputs

### File Handling

- Uploaded files may be in various formats: CSV, JSON, PDF, images, text files, etc.
- For spreadsheets and data files, examine the structure, columns, and sample data
- For documents, extract key information and requirements
- For images, analyze and describe their content
- For code files, understand the logic and patterns

**Do NOT ignore user uploaded files.** They are there for a reason and likely
contain exactly what you need to complete the task successfully."""


def build_org_info_section(include_org_info: bool) -> str:
    """Build the organization info section for AGENTS.md.

    Only includes the org_info section when demo data is enabled,
    since the org_info/ directory is only set up in that case.

    Args:
        include_org_info: Whether to include the org_info section

    Returns:
        Formatted org info section string, or empty string if not included
    """
    if include_org_info:
        return ORG_INFO_SECTION_CONTENT
    return ""


def extract_skill_description(skill_md_path: Path) -> str:
    """Extract a brief description from a SKILL.md file.

    If the file has YAML frontmatter (delimited by ---), uses the
    ``description`` field. Otherwise falls back to the first paragraph.

    Args:
        skill_md_path: Path to the SKILL.md file

    Returns:
        Brief description (truncated to ~120 chars)
    """
    try:
        content = skill_md_path.read_text()
        lines = content.strip().split("\n")

        # Try YAML frontmatter first
        if lines and lines[0].strip() == "---":
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if desc:
                        if len(desc) > 120:
                            desc = desc[:117] + "..."
                        return desc

        # Fallback: first non-heading paragraph after frontmatter
        in_frontmatter = lines[0].strip() == "---" if lines else False
        description_lines: list[str] = []
        for line in lines[1:] if in_frontmatter else lines:
            stripped = line.strip()
            # Skip until end of frontmatter
            if in_frontmatter:
                if stripped == "---":
                    in_frontmatter = False
                continue
            if not stripped:
                if description_lines:
                    break
                continue
            if stripped.startswith("#"):
                continue
            description_lines.append(stripped)
            if len(" ".join(description_lines)) > 100:
                break

        description = " ".join(description_lines)
        if len(description) > 120:
            description = description[:117] + "..."
        return description or "No description available."
    except Exception:
        return "No description available."


def _scan_skills_directory(skills_path: Path) -> str:
    """Internal function to scan skills directory (not cached).

    Args:
        skills_path: Path to the skills directory

    Returns:
        Formatted skills section string
    """
    skills_list: list[str] = []
    try:
        for skill_dir in sorted(skills_path.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            # Fall back to the un-rendered template so per-session skills
            # (like company-search) still surface a useful description before
            # they're materialized.
            if not skill_md.exists():
                skill_md_template = skill_dir / "SKILL.md.template"
                if skill_md_template.exists():
                    skill_md = skill_md_template

            if skill_md.exists():
                description = extract_skill_description(skill_md)
                skills_list.append(f"- **{skill_dir.name}**: {description}")
    except Exception as e:
        logger.warning(f"Error scanning skills directory: {e}")
        return "Error loading skills."

    if not skills_list:
        return "No skills available."

    return "\n".join(skills_list)


def build_skills_section(skills_path: Path) -> str:
    """Build the available skills section by scanning the skills directory.

    Skills are static, so results are cached indefinitely for performance.

    Args:
        skills_path: Path to the skills directory

    Returns:
        Formatted skills section string
    """
    if not skills_path.exists():
        return "No skills available."

    cache_key = str(skills_path)

    # Check cache first (skills are static, no TTL needed)
    with _skills_cache_lock:
        cached = _skills_cache.get(cache_key)
        if cached is not None:
            return cached

    # Cache miss - scan the directory
    result = _scan_skills_directory(skills_path)

    # Update cache
    with _skills_cache_lock:
        _skills_cache[cache_key] = result

    return result


def _safe_craft_description(source: DocumentSource, fallback: str) -> str:
    desc = DocumentSourceCraftDescription.get(source)
    if desc:
        return desc
    return fallback


def _format_available_sources(
    cc_pairs: list[ConnectorCredentialPair],
) -> str:
    """Render the user's accessible connectors as a bullet list for SKILL.md.

    One bullet per source id (deduplicated across multiple CC pairs that share
    a source). Uses ``DocumentSourceCraftDescription`` as the source of truth
    for what each source contains; falls back to the source id itself if a
    new connector landed without a description (shouldn't happen — see the
    coverage test — but we never crash on missing data).
    """
    seen: dict[str, str] = {}
    for cc_pair in cc_pairs:
        source = cc_pair.connector.source
        source_id = source.value
        if source_id in seen:
            continue
        seen[source_id] = _safe_craft_description(source, source_id)

    if not seen:
        return (
            "- _(no connectors are configured for this user — "
            "company_search will return no results until an admin connects a source)_"
        )

    lines = [f"- `{source_id}` — {desc}" for source_id, desc in sorted(seen.items())]
    # User-uploaded files always appear in `attachments/` regardless of
    # connector setup; mention them so the agent doesn't think uploads are gone.
    lines.append(
        "- `(user_uploads)` — Files the user attached to this session, under `attachments/`"
    )
    return "\n".join(lines)


def render_company_search_skill_md(
    user: User,
    db_session: Session,
    skill_template_path: Path,
) -> str:
    """Render the per-session company-search SKILL.md from a template.

    Templates live next to the skill bundle (``SKILL.md.template``) and are
    rendered into the materialized ``.opencode/skills/company-search/SKILL.md``
    at session setup. The rendered content is a snapshot — connectors added
    or removed mid-session are not reflected until the user starts a new
    session (see search.md design doc).
    """
    if not skill_template_path.exists():
        raise RuntimeError(
            f"company-search SKILL.md.template not found at {skill_template_path}"
        )

    template = skill_template_path.read_text()

    # Pull every CC pair the user can read — same source the
    # /api/build/connectors endpoint uses for the connector list.
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        eager_load_connector=True,
        processing_mode=None,
    )

    # Filter out non-connector sources (ingestion API, mock connector, etc.)
    visible_sources = {
        DocumentSource.SLACK,
        DocumentSource.WEB,
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.GMAIL,
        DocumentSource.GITHUB,
        DocumentSource.GITBOOK,
        DocumentSource.GITLAB,
        DocumentSource.BITBUCKET,
        DocumentSource.GURU,
        DocumentSource.BOOKSTACK,
        DocumentSource.OUTLINE,
        DocumentSource.CONFLUENCE,
        DocumentSource.JIRA,
        DocumentSource.SLAB,
        DocumentSource.PRODUCTBOARD,
        DocumentSource.NOTION,
        DocumentSource.LINEAR,
        DocumentSource.HUBSPOT,
        DocumentSource.DOCUMENT360,
        DocumentSource.GONG,
        DocumentSource.GOOGLE_SITES,
        DocumentSource.ZENDESK,
        DocumentSource.LOOPIO,
        DocumentSource.DROPBOX,
        DocumentSource.SHAREPOINT,
        DocumentSource.TEAMS,
        DocumentSource.SALESFORCE,
        DocumentSource.DISCOURSE,
        DocumentSource.AXERO,
        DocumentSource.CLICKUP,
        DocumentSource.MEDIAWIKI,
        DocumentSource.WIKIPEDIA,
        DocumentSource.ASANA,
        DocumentSource.S3,
        DocumentSource.R2,
        DocumentSource.GOOGLE_CLOUD_STORAGE,
        DocumentSource.OCI_STORAGE,
        DocumentSource.XENFORO,
        DocumentSource.DISCORD,
        DocumentSource.FRESHDESK,
        DocumentSource.FIREFLIES,
        DocumentSource.EGNYTE,
        DocumentSource.AIRTABLE,
        DocumentSource.HIGHSPOT,
        DocumentSource.DRUPAL_WIKI,
        DocumentSource.IMAP,
        DocumentSource.TESTRAIL,
        DocumentSource.REQUESTTRACKER,
        DocumentSource.CODA,
        DocumentSource.CANVAS,
        DocumentSource.ZULIP,
        DocumentSource.FILE,
        DocumentSource.USER_FILE,
        DocumentSource.CRAFT_FILE,
    }
    filtered_cc_pairs = [
        cc_pair for cc_pair in cc_pairs if cc_pair.connector.source in visible_sources
    ]

    sources_section = _format_available_sources(filtered_cc_pairs)
    return template.replace("{{AVAILABLE_SOURCES_SECTION}}", sources_section)


def generate_agent_instructions(
    template_path: Path,
    skills_path: Path,
    provider: str | None = None,
    model_name: str | None = None,
    nextjs_port: int | None = None,
    disabled_tools: list[str] | None = None,
    user_name: str | None = None,
    user_role: str | None = None,
    use_demo_data: bool = False,
    include_org_info: bool = False,
) -> str:
    """Generate AGENTS.md content by populating the template with dynamic values.

    Args:
        template_path: Path to the AGENTS.template.md file
        skills_path: Path to the skills directory
        provider: LLM provider type (e.g., "openai", "anthropic")
        model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
        nextjs_port: Port for Next.js development server
        disabled_tools: List of disabled tools
        user_name: User's name for personalization
        user_role: User's role/title for personalization
        use_demo_data: If True, exclude user context from AGENTS.md
        include_org_info: Whether to include the org_info section (demo data mode)

    Returns:
        Generated AGENTS.md content with placeholders replaced
    """
    if not template_path.exists():
        logger.warning(f"AGENTS.template.md not found at {template_path}")
        return "# Agent Instructions\n\nNo custom instructions provided."

    # Read template content
    template_content = template_path.read_text()

    # Build user context section - only include when NOT using demo data
    user_context = "" if use_demo_data else build_user_context(user_name, user_role)

    # Build LLM configuration section
    provider_display = get_provider_display_name(provider)

    # Build disabled tools section
    disabled_tools_section = ""
    if disabled_tools:
        disabled_tools_section = f"\n**Disabled Tools**: {', '.join(disabled_tools)}\n"

    # Build available skills section
    available_skills_section = build_skills_section(skills_path)

    # Build org info section (only included when demo data is enabled)
    org_info_section = build_org_info_section(include_org_info)

    # Replace placeholders
    content = template_content
    content = content.replace("{{USER_CONTEXT}}", user_context)
    content = content.replace("{{LLM_PROVIDER_NAME}}", provider_display or "Unknown")
    content = content.replace("{{LLM_MODEL_NAME}}", model_name or "Unknown")
    content = content.replace(
        "{{NEXTJS_PORT}}", str(nextjs_port) if nextjs_port else "Unknown"
    )
    content = content.replace("{{DISABLED_TOOLS_SECTION}}", disabled_tools_section)
    content = content.replace("{{AVAILABLE_SKILLS_SECTION}}", available_skills_section)
    content = content.replace("{{ORG_INFO_SECTION}}", org_info_section)

    return content
