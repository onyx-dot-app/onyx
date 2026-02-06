#!/usr/bin/env python3
"""Generate AGENTS.md by scanning the files directory and populating the template.

This script runs at container startup, AFTER the init container has synced files
from S3. It scans the /workspace/files directory to discover what knowledge sources
are available and generates appropriate documentation.

Environment variables:
- AGENT_INSTRUCTIONS: The template content with placeholders to replace
"""

import os
import sys
from pathlib import Path

# Type alias for connector info entries
ConnectorInfoEntry = dict[str, str | int]

# Connector information for generating knowledge sources section
# Keys are normalized (lowercase, underscores) directory names
# Each entry has: summary (with optional {subdirs}), file_pattern, scan_depth
# NOTE: This is duplicated from agent_instructions.py to avoid circular imports
CONNECTOR_INFO: dict[str, ConnectorInfoEntry] = {
    "google_drive": {
        "summary": "Documents and files from Google Drive. This may contain information about a user and work they have done.",
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
    "org_info": {
        "summary": "Organizational structure and user identity",
        "file_pattern": "Various JSON files",
        "scan_depth": 0,
    },
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


def build_knowledge_sources_section(files_path: Path) -> str:
    """Build combined knowledge sources section with summary, structure, and file patterns.

    This creates a single section per connector that includes:
    - What kind of data it contains (with actual subdirectory names)
    - The directory structure
    - The file naming pattern

    Args:
        files_path: Path to the files directory

    Returns:
        Formatted knowledge sources section
    """
    if not files_path.exists():
        return "No knowledge sources available."

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
        print(
            f"Warning: Error building knowledge sources section: {e}", file=sys.stderr
        )
        return "Error scanning knowledge sources."

    if not sections:
        return "No knowledge sources available."

    return "\n\n".join(sections)


def main() -> None:
    """Main entry point for container startup script.

    Is called by the container startup script to scan /workspace/files and populate
    the knowledge sources section.
    """
    # Read template from environment variable
    template = os.environ.get("AGENT_INSTRUCTIONS", "")
    if not template:
        print("Warning: No AGENT_INSTRUCTIONS template provided", file=sys.stderr)
        template = "# Agent Instructions\n\nNo instructions provided."

    # Scan files directory - check /workspace/files first, then /workspace/demo_data
    files_path = Path("/workspace/files")
    demo_data_path = Path("/workspace/demo_data")

    # Use demo_data if files doesn't exist or is empty
    if not files_path.exists() or not any(files_path.iterdir()):
        if demo_data_path.exists():
            files_path = demo_data_path

    knowledge_sources_section = build_knowledge_sources_section(files_path)

    # Replace placeholders
    content = template
    content = content.replace(
        "{{KNOWLEDGE_SOURCES_SECTION}}", knowledge_sources_section
    )

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
    print(
        f"Generated AGENTS.md with {source_count} knowledge sources from {files_path}"
    )


if __name__ == "__main__":
    main()
