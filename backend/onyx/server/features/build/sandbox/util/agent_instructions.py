"""Shared utilities for generating AGENTS.md content."""

import json
from collections.abc import Iterable
from pathlib import Path

from onyx.db.models import ExternalApp
from onyx.server.features.build.configs import (
    SANDBOX_APPROVAL_WAIT_MARGIN_SECONDS,
    SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

AGENT_INSTRUCTIONS_TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent / "AGENTS.template.md"
)

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

The `attachments/` directory stores session files. Its contents are not the
current task's selections.

Use only the attachment paths selected in the current message as required
context. Read those files before completing the task. Earlier message
attachments remain available when the task refers to them. Do not read every
stored file or infer that a stored file was selected for the current task."""


def build_attachment_prompt(content: str, paths: Iterable[str]) -> str:
    """Add explicitly selected file paths to the agent's task context."""
    selected_paths: list[str] = list(paths)
    selection: str = (
        "\n".join(f"- {json.dumps(path)}" for path in selected_paths)
        if selected_paths
        else "None."
    )
    return (
        content
        + "\n\nSelected attachments for this task (read these files):\n"
        + selection
        + "\nStored files are not current selections. Do not read unselected files "
        "unless this task refers to earlier attachments. This selection replaces "
        "any instruction to read every file in attachments/."
    )


def build_connectable_apps_list(apps: Iterable[ExternalApp]) -> str:
    """Render the connectable-apps bullet list — org apps the user hasn't set up
    yet. The heading and explanatory prose live in AGENTS.template.md; this only
    supplies the dynamic ``{{CONNECTABLE_APPS_LIST}}`` value, with a fallback
    line when there are no apps."""
    entries = sorted((app.id, app.name) for app in apps)
    if not entries:
        return "No connectable apps available."
    return "\n".join(
        f"- External app ID `{external_app_id}`: **{name}**"
        for external_app_id, name in entries
    )


def build_organization_instructions_section(instructions: str | None) -> str:
    if not instructions or not instructions.strip():
        return ""
    return (
        "\n## Organization instructions\n\n"
        "Your organization's admins set these workspace-wide instructions. "
        "Follow them in every session; the Hard rules above still win on any "
        "conflict.\n\n"
        f"{instructions.strip()}\n"
    )


def generate_agent_instructions(
    template_path: Path,
    connectable_apps_section: str,
    provider: str | None = None,
    model_name: str | None = None,
    disabled_tools: list[str] | None = None,
    user_name: str | None = None,
    organization_instructions: str | None = None,
) -> str:
    """Generate AGENTS.md content by populating the template with dynamic values.

    Args:
        template_path: Path to the AGENTS.template.md file
        connectable_apps_section: Pre-rendered connectable-apps list (may be empty)
        provider: LLM provider type (e.g., "openai", "anthropic")
        model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
        disabled_tools: List of disabled tools
        user_name: User's name for personalization
        organization_instructions: Admin-set workspace-wide Craft instructions

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
        "{{APPROVAL_WAIT_TIMEOUT_SECONDS}}",
        str(SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS),
    )
    content = content.replace(
        "{{APPROVAL_CLIENT_TIMEOUT_SECONDS}}",
        str(
            SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS + SANDBOX_APPROVAL_WAIT_MARGIN_SECONDS
        ),
    )
    content = content.replace("{{DISABLED_TOOLS_SECTION}}", disabled_tools_section)
    content = content.replace("{{CONNECTABLE_APPS_LIST}}", connectable_apps_section)
    # Last, so admin-authored text containing literal {{...}} tokens (e.g.
    # copy-pasted from the base template) is never expanded.
    content = content.replace(
        "{{ORGANIZATION_INSTRUCTIONS_SECTION}}",
        build_organization_instructions_section(organization_instructions),
    )

    return content
