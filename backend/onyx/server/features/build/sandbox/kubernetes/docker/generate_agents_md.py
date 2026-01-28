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

from .agent_content import ATTACHMENTS_SECTION_CONTENT
from .agent_content import CONNECTOR_DESCRIPTIONS


def build_attachments_section(attachments_path: Path) -> str:
    """Return attachments section if files exist, empty string otherwise."""
    if not attachments_path.exists():
        return ""
    try:
        if any(attachments_path.iterdir()):
            return ATTACHMENTS_SECTION_CONTENT
    except Exception:
        pass
    return ""


def build_file_structure_section(files_path: Path) -> str:
    """Build the file structure section by scanning the files directory."""
    if not files_path.exists():
        return "No knowledge sources available."

    sources = []
    try:
        for item in sorted(files_path.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            file_count = sum(1 for f in item.rglob("*") if f.is_file())
            subdir_count = sum(1 for d in item.rglob("*") if d.is_dir())

            details = []
            if file_count > 0:
                details.append(f"{file_count} file{'s' if file_count != 1 else ''}")
            if subdir_count > 0:
                details.append(
                    f"{subdir_count} subdirector{'ies' if subdir_count != 1 else 'y'}"
                )

            source_info = f"- **{item.name}/**"
            if details:
                source_info += f" ({', '.join(details)})"
            sources.append(source_info)
    except Exception as e:
        print(f"Warning: Error scanning files directory: {e}", file=sys.stderr)
        return "Error scanning knowledge sources."

    if not sources:
        return "No knowledge sources available."

    header = "The `files/` directory contains the following knowledge sources:\n\n"
    return header + "\n".join(sources)


def build_connector_descriptions(files_path: Path) -> str:
    """Build connector-specific descriptions for available data sources."""
    if not files_path.exists():
        return ""

    descriptions = []
    try:
        for item in sorted(files_path.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            normalized = item.name.lower().replace(" ", "_").replace("-", "_")
            if normalized in CONNECTOR_DESCRIPTIONS:
                descriptions.append(f"- {CONNECTOR_DESCRIPTIONS[normalized]}")
    except Exception as e:
        print(
            f"Warning: Error scanning for connector descriptions: {e}", file=sys.stderr
        )
        return ""

    if not descriptions:
        return ""

    header = "Each connector type organizes its data differently:\n\n"
    footer = "\n\nSpaces in names are replaced by `_`."
    return header + "\n".join(descriptions) + footer


def main() -> None:
    # Read template from environment variable
    template = os.environ.get("AGENT_INSTRUCTIONS", "")
    if not template:
        print("Warning: No AGENT_INSTRUCTIONS template provided", file=sys.stderr)
        template = "# Agent Instructions\n\nNo instructions provided."

    # Scan files directory
    files_path = Path("/workspace/files")
    file_structure = build_file_structure_section(files_path)
    connector_descriptions = build_connector_descriptions(files_path)

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
