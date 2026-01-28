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

# Connector descriptions for known connector types
# Keep in sync with agent_instructions.py CONNECTOR_DESCRIPTIONS
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
    "org_info": (
        "**Org Info**: Contains organizational data and identity information."
    ),
}


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

    # Replace placeholders
    content = template
    content = content.replace("{{FILE_STRUCTURE_SECTION}}", file_structure)
    content = content.replace(
        "{{CONNECTOR_DESCRIPTIONS_SECTION}}", connector_descriptions
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
    print(f"Generated AGENTS.md with {source_count} knowledge sources")


if __name__ == "__main__":
    main()
