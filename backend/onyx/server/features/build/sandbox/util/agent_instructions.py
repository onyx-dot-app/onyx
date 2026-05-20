"""Shared utilities for generating AGENTS.md content."""

from collections.abc import Iterable
from pathlib import Path

from onyx.db.models import Skill
from onyx.skills.registry import BuiltinSkill
from onyx.utils.logger import setup_logger

logger = setup_logger()

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


# Content for the org_info section when user_work_area is provided
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

    Included when user_work_area is provided and the org_info/
    directory is set up in the session.
    """
    if include_org_info:
        return ORG_INFO_SECTION_CONTENT
    return ""


_DESCRIPTION_MAX_LEN = 120


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > _DESCRIPTION_MAX_LEN:
        return text[: _DESCRIPTION_MAX_LEN - 3] + "..."
    return text


def build_skills_section_from_data(
    builtins: Iterable[BuiltinSkill],
    customs: Iterable[Skill],
) -> str:
    """Render the AGENTS.md skills section from registry + DB rows."""
    entries: list[tuple[str, str]] = []
    for b in builtins:
        entries.append((b.slug, _truncate(b.description)))
    for c in customs:
        entries.append((c.slug, _truncate(c.description)))

    if not entries:
        return "No skills available."

    entries.sort(key=lambda e: e[0])
    return "\n".join(f"- **{slug}**: {desc}" for slug, desc in entries)


def generate_agent_instructions(
    template_path: Path,
    skills_section: str,
    provider: str | None = None,
    model_name: str | None = None,
    nextjs_port: int | None = None,
    disabled_tools: list[str] | None = None,
    user_name: str | None = None,
    user_role: str | None = None,
    include_org_info: bool = False,
) -> str:
    """Generate AGENTS.md content by populating the template with dynamic values.

    Args:
        template_path: Path to the AGENTS.template.md file
        skills_section: Pre-rendered skills section
        provider: LLM provider type (e.g., "openai", "anthropic")
        model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
        nextjs_port: Port for Next.js development server
        disabled_tools: List of disabled tools
        user_name: User's name for personalization
        user_role: User's role/title for personalization
        include_org_info: Whether to include the org_info section

    Returns:
        Generated AGENTS.md content with placeholders replaced
    """
    if not template_path.exists():
        logger.warning("AGENTS.template.md not found at %s", template_path)
        return "# Agent Instructions\n\nNo custom instructions provided."

    template_content = template_path.read_text()

    user_context = build_user_context(user_name, user_role)

    # Build LLM configuration section
    provider_display = get_provider_display_name(provider)

    # Build disabled tools section
    disabled_tools_section = ""
    if disabled_tools:
        disabled_tools_section = f"\n**Disabled Tools**: {', '.join(disabled_tools)}\n"

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
    content = content.replace("{{AVAILABLE_SKILLS_SECTION}}", skills_section)
    content = content.replace("{{ORG_INFO_SECTION}}", org_info_section)

    return content
