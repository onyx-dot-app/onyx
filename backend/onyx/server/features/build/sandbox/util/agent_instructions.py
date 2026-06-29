"""Shared utilities for generating AGENTS.md content."""

from collections.abc import Iterable
from pathlib import Path

from onyx.db.models import ExternalApp
from onyx.db.models import Skill
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
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


_DESCRIPTION_MAX_LEN = 120


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > _DESCRIPTION_MAX_LEN:
        return text[: _DESCRIPTION_MAX_LEN - 3] + "..."
    return text


def build_skills_section_from_data(skills: Iterable[Skill]) -> str:
    """Render the AGENTS.md skills section from one unified list of
    ``Skill`` rows. Built-ins and customs are indistinguishable here —
    both show up as ``- **slug**: description`` bullets."""
    entries = [(s.slug, _truncate(s.description)) for s in skills]
    if not entries:
        return "No skills available."

    entries.sort(key=lambda e: e[0])
    return "\n".join(f"- **{slug}**: {desc}" for slug, desc in entries)


def build_connectable_apps_list(apps: Iterable[ExternalApp]) -> str:
    """Render the connectable-apps bullet list — org apps the user hasn't set up
    yet. The heading and explanatory prose live in AGENTS.template.md; this only
    supplies the dynamic ``{{CONNECTABLE_APPS_LIST}}`` value. Mirrors
    ``build_skills_section_from_data``: a fallback line when there's nothing."""
    entries = sorted((app.skill.slug, _truncate(app.skill.description)) for app in apps)
    if not entries:
        return "No connectable apps available."
    return "\n".join(f"- **{slug}**: {desc}" for slug, desc in entries)


def generate_agent_instructions(
    template_path: Path,
    skills_section: str,
    connectable_apps_section: str,
    provider: str | None = None,
    model_name: str | None = None,
    nextjs_port: int | None = None,
    disabled_tools: list[str] | None = None,
    user_name: str | None = None,
) -> str:
    """Generate AGENTS.md content by populating the template with dynamic values.

    Args:
        template_path: Path to the AGENTS.template.md file
        skills_section: Pre-rendered skills section
        connectable_apps_section: Pre-rendered connectable-apps list (may be empty)
        provider: LLM provider type (e.g., "openai", "anthropic")
        model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
        nextjs_port: Port for Next.js development server
        disabled_tools: List of disabled tools
        user_name: User's name for personalization

    Returns:
        Generated AGENTS.md content with placeholders replaced
    """
    if not template_path.exists():
        logger.warning("AGENTS.template.md not found at %s", template_path)
        return "# Agent Instructions\n\nNo custom instructions provided."

    template_content = template_path.read_text()

    if not user_name:
        user_context = ""
    else:
        user_context = f"You are assisting **{user_name}** with their work."

    # Build LLM configuration section
    provider_display = get_provider_display_name(provider)

    # Build disabled tools section
    disabled_tools_section = ""
    if disabled_tools:
        disabled_tools_section = f"\n**Disabled Tools**: {', '.join(disabled_tools)}\n"

    # Replace placeholders
    content = template_content
    content = content.replace("{{USER_CONTEXT}}", user_context)
    content = content.replace("{{LLM_PROVIDER_NAME}}", provider_display or "Unknown")
    content = content.replace("{{LLM_MODEL_NAME}}", model_name or "Unknown")
    content = content.replace(
        "{{NEXTJS_PORT}}", str(nextjs_port) if nextjs_port else "Unknown"
    )
    content = content.replace(
        "{{APPROVAL_WAIT_TIMEOUT_SECONDS}}",
        str(SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS),
    )
    content = content.replace(
        "{{APPROVAL_CLIENT_TIMEOUT_SECONDS}}",
        str(SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + 20),
    )
    content = content.replace("{{DISABLED_TOOLS_SECTION}}", disabled_tools_section)
    content = content.replace("{{AVAILABLE_SKILLS_SECTION}}", skills_section)
    content = content.replace("{{CONNECTABLE_APPS_LIST}}", connectable_apps_section)

    return content
