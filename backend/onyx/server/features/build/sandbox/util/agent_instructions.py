"""Shared utilities for generating AGENTS.md content.

This module provides functions for building dynamic agent instructions
that are shared between local and kubernetes sandbox managers.
"""

from pathlib import Path

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

# Connector directory structure descriptions
# Keys are normalized (lowercase, underscores) directory names
CONNECTOR_DESCRIPTIONS = {
    "google_drive": (
        "**Google Drive**: Copied over directly as is. "
        "End files are stored as `FILE_NAME.json`."
    ),
    "gmail": (
        "**Gmail**: Copied over directly as is. "
        "End files are stored as `FILE_NAME.json`."
    ),
    "linear": (
        "**Linear**: Each project is a folder, and within each project, "
        "individual tickets are stored as `[TICKET_ID]_TICKET_NAME.json`."
    ),
    "slack": (
        "**Slack**: Each channel is a folder titled `[CHANNEL_NAME]`. "
        "Within each channel, each thread is a single file called "
        "`[INITIAL_AUTHOR]_in_[CHANNEL]__[FIRST_MESSAGE].json`."
    ),
    "github": (
        "**Github**: Each organization is a folder titled `[ORG_NAME]`. "
        "Within each organization, there is a folder for each repository "
        "titled `[REPO_NAME]`. Within each repository there are up to two "
        "folders: `pull_requests` and `issues`. Pull requests are structured "
        "as `[PR_ID]__[PR_NAME].json` and issues as `[ISSUE_ID]__[ISSUE_NAME].json`."
    ),
    "fireflies": (
        "**Fireflies**: All calls are in the root, each as a single file "
        "titled `CALL_TITLE.json`."
    ),
    "hubspot": (
        "**HubSpot**: Four folders in the root: `Tickets`, `Companies`, "
        "`Deals`, and `Contacts`. Each object is stored as a file named "
        "after its title/name (e.g., `[TICKET_SUBJECT].json`, `[COMPANY_NAME].json`)."
    ),
    "notion": (
        "**Notion**: Pages and databases are organized hierarchically. "
        "Each page is stored as `PAGE_TITLE.json`."
    ),
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

    Looks for the first paragraph or heading content.

    Args:
        skill_md_path: Path to the SKILL.md file

    Returns:
        Brief description (truncated to ~100 chars)
    """
    try:
        content = skill_md_path.read_text()
        lines = content.strip().split("\n")

        # Skip empty lines and the first heading
        description_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
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


def build_skills_section(skills_path: Path) -> str:
    """Build the available skills section by scanning the skills directory.

    Args:
        skills_path: Path to the skills directory

    Returns:
        Formatted skills section string
    """
    if not skills_path.exists():
        return "No skills available."

    skills_list: list[str] = []
    try:
        for skill_dir in skills_path.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                description = extract_skill_description(skill_md)
                skills_list.append(f"- **{skill_dir.name}**: {description}")
    except Exception as e:
        logger.warning(f"Error scanning skills directory: {e}")
        return "Error loading skills."

    if not skills_list:
        return "No skills available."

    return "\n".join(skills_list)


def _normalize_connector_name(name: str) -> str:
    """Normalize a connector directory name for lookup.

    Args:
        name: The directory name

    Returns:
        Normalized name (lowercase, spaces to underscores)
    """
    return name.lower().replace(" ", "_").replace("-", "_")


def build_file_structure_section(files_path: Path) -> str:
    """Build the file structure section by scanning the files directory.

    Scans the symlinked files/ directory to discover which data sources
    are available and lists them for the agent.

    Args:
        files_path: Path to the files directory (symlink to knowledge sources)

    Returns:
        Formatted file structure section string describing available sources
    """
    if not files_path.exists():
        return "No knowledge sources available."

    # Resolve the symlink to get the actual path
    try:
        actual_path = files_path.resolve()
        if not actual_path.exists():
            return "No knowledge sources available."
    except Exception:
        # If we can't resolve the symlink, try to use it directly
        actual_path = files_path

    sources: list[str] = []
    try:
        for item in sorted(actual_path.iterdir()):
            if not item.is_dir():
                continue
            # Skip hidden directories
            if item.name.startswith("."):
                continue

            source_name = item.name
            # Count files and subdirectories for context
            file_count = 0
            subdir_count = 0
            try:
                for child in item.rglob("*"):
                    if child.is_file():
                        file_count += 1
                    elif child.is_dir():
                        subdir_count += 1
            except Exception:
                pass

            # Build description based on source name
            source_info = f"- **{source_name}/**"
            if file_count > 0 or subdir_count > 0:
                details = []
                if file_count > 0:
                    details.append(f"{file_count} file{'s' if file_count != 1 else ''}")
                if subdir_count > 0:
                    details.append(
                        f"{subdir_count} subdirector{'ies' if subdir_count != 1 else 'y'}"
                    )
                source_info += f" ({', '.join(details)})"

            sources.append(source_info)
    except Exception as e:
        logger.warning(f"Error scanning files directory: {e}")
        return "Error loading knowledge sources."

    if not sources:
        return "No knowledge sources available."

    header = "The `files/` directory contains the following knowledge sources:\n\n"
    return header + "\n".join(sources)


def build_connector_descriptions_section(files_path: Path) -> str:
    """Build connector-specific descriptions for available data sources.

    Only includes descriptions for connectors that are actually present
    in the files/ directory.

    Args:
        files_path: Path to the files directory (symlink to knowledge sources)

    Returns:
        Formatted connector descriptions section
    """
    if not files_path.exists():
        return ""

    # Resolve the symlink to get the actual path
    try:
        actual_path = files_path.resolve()
        if not actual_path.exists():
            return ""
    except Exception:
        actual_path = files_path

    descriptions: list[str] = []
    try:
        for item in sorted(actual_path.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith("."):
                continue

            # Look up connector description
            normalized_name = _normalize_connector_name(item.name)
            if normalized_name in CONNECTOR_DESCRIPTIONS:
                descriptions.append(f"- {CONNECTOR_DESCRIPTIONS[normalized_name]}")
    except Exception as e:
        logger.warning(
            f"Error scanning files directory for connector descriptions: {e}"
        )
        return ""

    if not descriptions:
        return ""

    header = "Each connector type organizes its data differently:\n\n"
    footer = "\n\nAcross all names, spaces are replaced by `_`."
    return header + "\n".join(descriptions) + footer


def generate_agent_instructions(
    template_path: Path,
    skills_path: Path,
    files_path: Path | None = None,
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
        files_path: Path to the files directory (symlink to knowledge sources)
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

    # Only replace file-related placeholders if files_path is provided.
    # When files_path is None (e.g., Kubernetes), leave placeholders intact
    # so the container can replace them after files are synced.
    if files_path:
        file_structure_section = build_file_structure_section(files_path)
        connector_descriptions_section = build_connector_descriptions_section(
            files_path
        )
        content = content.replace("{{FILE_STRUCTURE_SECTION}}", file_structure_section)
        content = content.replace(
            "{{CONNECTOR_DESCRIPTIONS_SECTION}}", connector_descriptions_section
        )

    return content
