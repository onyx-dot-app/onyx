#!/usr/bin/env python3
"""Generate AGENTS.md by scanning the files directory and populating the template.

This script runs at container startup, AFTER the init container has synced files
from S3. It scans the /workspace/files directory to discover what knowledge sources
are available and generates appropriate documentation.

The core scanning functions are also imported by agent_instructions.py for use
in the local sandbox manager.

Environment variables:
- AGENT_INSTRUCTIONS: The template content with placeholders to replace
"""

import os
import sys
from pathlib import Path

# Connector descriptions for known connector types (condensed for token efficiency)
# Keep in sync with agent_instructions.py CONNECTOR_DESCRIPTIONS
# NOTE: This is duplicated to avoid circular imports
CONNECTOR_DESCRIPTIONS = {
    "google_drive": "**Google Drive**: Files stored as `FILE_NAME.json`.",
    "gmail": "**Gmail**: Files stored as `FILE_NAME.json`.",
    "linear": "**Linear**: `[TEAM]/[TICKET_ID]_TICKET_TITLE.json`.",
    "slack": "**Slack**: `[CHANNEL]/[AUTHOR]_in_[CHANNEL]__[MSG].json`.",
    "github": "**Github**: `[ORG]/[REPO]/pull_requests/[PR_NUMBER]__[PR_TITLE].json`.",
    "fireflies": "**Fireflies**: `[YYYY-MM]/CALL_TITLE.json` organized by month.",
    "hubspot": "**HubSpot**: `Tickets/`, `Companies/`, `Deals/`, `Contacts/` folders.",
    "notion": "**Notion**: Hierarchical pages as `PAGE_TITLE.json`.",
    "org_info": "**Org Info**: Organizational data and identity information.",
}

# Content for the attachments section when user has uploaded files
# NOTE: This is duplicated in agent_instructions.py to avoid circular imports
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


def normalize_connector_name(name: str) -> str:
    """Normalize a connector directory name for lookup.

    Args:
        name: The directory name

    Returns:
        Normalized name (lowercase, spaces to underscores)
    """
    return name.lower().replace(" ", "_").replace("-", "_")


def build_attachments_section(attachments_path: Path) -> str:
    """Return attachments section if files exist, empty string otherwise.

    Args:
        attachments_path: Path to the attachments directory

    Returns:
        Attachments section content or empty string
    """
    if not attachments_path.exists():
        return ""
    try:
        if any(attachments_path.iterdir()):
            return ATTACHMENTS_SECTION_CONTENT
    except Exception:
        pass
    return ""


# Per-connector directory scan depth (0 = just connector name, 1 = one level, 2 = two levels)
CONNECTOR_SCAN_DEPTH = {
    "google_drive": 0,  # Don't look into folders
    "gmail": 0,  # Don't look into folders
    "fireflies": 1,  # Show YYYY-MM folders only
    "linear": 2,  # Linear/TEAM/issues
    "github": 2,  # Github/ORG/pull_requests
    "slack": 1,  # Show channels
    "hubspot": 1,  # Show Tickets/, Companies/, etc.
    "notion": 1,  # Show top-level pages
    "org_info": 0,  # Don't look into folders
}
DEFAULT_SCAN_DEPTH = 1


def _normalize_connector_name(name: str) -> str:
    """Normalize a connector directory name for lookup."""
    return name.lower().replace(" ", "_").replace("-", "_")


def _scan_directory_to_depth(
    directory: Path, current_depth: int, max_depth: int, indent: str = "  "
) -> list[str]:
    """Recursively scan directory up to max_depth levels."""
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


def build_file_structure_section(files_path: Path) -> str:
    """Build the file structure section with per-connector depth rules."""
    if not files_path.exists():
        return "No knowledge sources available."

    sources: list[str] = []
    try:
        for item in sorted(files_path.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            sources.append(f"- **{item.name}/**")

            # Get scan depth for this connector
            normalized = _normalize_connector_name(item.name)
            max_depth = CONNECTOR_SCAN_DEPTH.get(normalized, DEFAULT_SCAN_DEPTH)

            # Scan subdirectories up to max_depth
            nested = _scan_directory_to_depth(item, 0, max_depth, "  ")
            sources.extend(nested)
    except Exception as e:
        print(f"Warning: Error scanning files directory: {e}", file=sys.stderr)
        return "Error scanning knowledge sources."

    if not sources:
        return "No knowledge sources available."

    header = "The `files/` directory contains:\n\n"
    return header + "\n".join(sources)


def build_connector_descriptions_section(files_path: Path) -> str:
    """Build connector-specific descriptions for available data sources.

    Args:
        files_path: Path to the files directory

    Returns:
        Formatted connector descriptions section
    """
    if not files_path.exists():
        return ""

    descriptions: list[str] = []
    try:
        for item in sorted(files_path.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            normalized = _normalize_connector_name(item.name)
            if normalized in CONNECTOR_DESCRIPTIONS:
                descriptions.append(f"- {CONNECTOR_DESCRIPTIONS[normalized]}")
    except Exception as e:
        print(
            f"Warning: Error scanning for connector descriptions: {e}", file=sys.stderr
        )
        return ""

    if not descriptions:
        return ""

    header = "### Connector Structures\n\n"
    return header + "\n".join(descriptions)


def main() -> None:
    """Main entry point for container startup script."""
    # Read template from environment variable
    template = os.environ.get("AGENT_INSTRUCTIONS", "")
    if not template:
        print("Warning: No AGENT_INSTRUCTIONS template provided", file=sys.stderr)
        template = "# Agent Instructions\n\nNo instructions provided."

    # Scan files directory
    files_path = Path("/workspace/files")
    file_structure = build_file_structure_section(files_path)
    connector_descriptions = build_connector_descriptions_section(files_path)

    # Check attachments directory
    attachments_path = Path("/workspace/attachments")
    attachments_section = build_attachments_section(attachments_path)

    # Replace placeholders
    content = template
    content = content.replace("{{FILE_STRUCTURE_SECTION}}", file_structure)
    content = content.replace(
        "{{CONNECTOR_DESCRIPTIONS_SECTION}}", connector_descriptions
    )
    content = content.replace("{{ATTACHMENTS_SECTION}}", attachments_section)

    # Write AGENTS.md
    output_path = Path("/workspace/AGENTS.md")
    output_path.write_text(content)

    # Log result
    source_count = 0
    if files_path.exists():
        source_count = len(
            [
                d
                for d in files_path.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ]
        )
    print(f"Generated AGENTS.md with {source_count} knowledge sources")


if __name__ == "__main__":
    main()
