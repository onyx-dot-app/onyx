"""Shared utilities for generating AGENTS.md content.

This module provides functions for building dynamic agent instructions
that are shared between local and kubernetes sandbox managers.
"""

import threading
from pathlib import Path

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

# Type alias for connector info entries
ConnectorInfoEntry = dict[str, str | int]

# Connector information for generating knowledge sources section
# Keys are normalized (lowercase, underscores) directory names
# Each entry has: summary (with optional {subdirs}), file_pattern, scan_depth
# NOTE: This is duplicated in kubernetes/docker/generate_agents_md.py to avoid circular imports
CONNECTOR_INFO: dict[str, ConnectorInfoEntry] = {
    "google_drive": {
        "summary": "Documents and files from Google Drive. This may contain information about a user and work they have done",
        "file_pattern": "`FILE_NAME.json`",
        "scan_depth": 0,
    },
    "gmail": {
        "summary": "Email conversations and threads",
        "file_pattern": "`FILE_NAME.json`",
        "scan_depth": 0,
    },
    "linear": {
        "summary": "Engineering tickets from teams: {subdirs}",
        "file_pattern": "`[TEAM]/[TICKET_ID]_TICKET_TITLE.json`",
        "scan_depth": 2,
    },
    "slack": {
        "summary": "Team messages from channels: {subdirs}",
        "file_pattern": "`[CHANNEL]/[AUTHOR]_in_[CHANNEL]__[MSG].json`",
        "scan_depth": 1,
    },
    "github": {
        "summary": "Pull requests and code from: {subdirs}",
        "file_pattern": "`[ORG]/[REPO]/pull_requests/[PR_NUMBER]__[PR_TITLE].json`",
        "scan_depth": 2,
    },
    "fireflies": {
        "summary": "Meeting transcripts from: {subdirs}",
        "file_pattern": "`[YYYY-MM]/CALL_TITLE.json`",
        "scan_depth": 1,
    },
    "hubspot": {
        "summary": "CRM data including: {subdirs}",
        "file_pattern": "`[TYPE]/[RECORD_NAME].json`",
        "scan_depth": 1,
    },
    "notion": {
        "summary": "Documentation and notes: {subdirs}",
        "file_pattern": "`PAGE_TITLE.json`",
        "scan_depth": 1,
    },
    "user_library": {
        "summary": "User-uploaded files (spreadsheets, documents, presentations, etc.)",
        "file_pattern": "Any file format",
        "scan_depth": 1,
    },
}
DEFAULT_SCAN_DEPTH = 1


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


def _normalize_connector_name(name: str) -> str:
    """Normalize a connector directory name for lookup."""
    return name.lower().replace(" ", "_").replace("-", "_")


def _scan_directory_to_depth(
    directory: Path, current_depth: int, max_depth: int, indent: str = "  "
) -> list[str]:
    """Recursively scan directory up to max_depth levels.

    Args:
        directory: Directory to scan
        current_depth: Current depth level (0 = connector root)
        max_depth: Maximum depth to scan
        indent: Indentation string for current level

    Returns:
        List of formatted directory lines
    """
    if current_depth >= max_depth:
        return []

    lines: list[str] = []
    try:
        subdirs = sorted(
            d for d in directory.iterdir() if d.is_dir() and not d.name.startswith(".")
        )

        for subdir in subdirs[:10]:  # Limit to 10 per level
            lines.append(f"{indent}- {subdir.name}/")

            # Recurse if we haven't hit max depth
            if current_depth + 1 < max_depth:
                nested = _scan_directory_to_depth(
                    subdir, current_depth + 1, max_depth, indent + "  "
                )
                lines.extend(nested)

        if len(subdirs) > 10:
            lines.append(f"{indent}- ... and {len(subdirs) - 10} more")
    except Exception:
        pass

    return lines


def build_knowledge_sources_section(files_path: Path) -> str:
    """Build combined knowledge sources section with summary, structure, and file patterns.

    This creates a single section per connector that includes:
    - What kind of data it contains (with actual subdirectory names)
    - The directory structure
    - The file naming pattern

    Args:
        files_path: Path to the files directory (symlink to knowledge sources)

    Returns:
        Formatted knowledge sources section
    """
    if not files_path.exists():
        return "No knowledge sources available."

    # Resolve the symlink to get the actual path
    try:
        actual_path = files_path.resolve()
        if not actual_path.exists():
            return "No knowledge sources available."
    except Exception:
        actual_path = files_path

    sections: list[str] = []
    try:
        for item in sorted(files_path.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            normalized = _normalize_connector_name(item.name)
            info = CONNECTOR_INFO.get(normalized, {})

            # Get subdirectory names
            subdirs: list[str] = []
            try:
                subdirs = sorted(
                    d.name
                    for d in item.iterdir()
                    if d.is_dir() and not d.name.startswith(".")
                )[:5]
            except Exception:
                pass

            # Build summary with subdirs
            summary_template = str(info.get("summary", f"Data from {item.name}"))
            if "{subdirs}" in summary_template and subdirs:
                subdir_str = ", ".join(subdirs)
                if len(subdirs) == 5:
                    subdir_str += ", ..."
                summary = summary_template.format(subdirs=subdir_str)
            elif "{subdirs}" in summary_template:
                summary = summary_template.replace(": {subdirs}", "").replace(
                    " {subdirs}", ""
                )
            else:
                summary = summary_template

            # Build connector section
            file_pattern = str(info.get("file_pattern", ""))
            scan_depth = int(info.get("scan_depth", DEFAULT_SCAN_DEPTH))

            lines = [f"### {item.name}/"]
            lines.append(f"{summary}.\n")
            # Add directory structure if depth > 0
            if scan_depth > 0:
                lines.append("Directory structure:\n")
                nested = _scan_directory_to_depth(item, 0, scan_depth, "")
                if nested:
                    lines.append("")
                    lines.extend(nested)

            lines.append(f"\nFile format: {file_pattern}")

            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(f"Error building knowledge sources section: {e}")
        return "Error scanning knowledge sources."

    if not sections:
        return "No knowledge sources available."

    return "\n\n".join(sections)


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
        knowledge_sources_section = build_knowledge_sources_section(files_path)
        content = content.replace(
            "{{KNOWLEDGE_SOURCES_SECTION}}", knowledge_sources_section
        )

    return content
