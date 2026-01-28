"""Shared content constants for AGENTS.md generation.

This module contains content strings used across different sandbox implementations.
It avoids circular imports by not importing anything from the sandbox system.
"""

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
    "org_info": (
        "**Org Info**: Contains organizational data and identity information."
    ),
}

# Content for the attachments section when user has uploaded files
ATTACHMENTS_SECTION_CONTENT = """## Attachments (PRIORITY)

The `attachments/` directory contains files that the user has explicitly uploaded during this session.
**These files are critically important** and should be treated as high-priority context.

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

**Do NOT ignore user uploaded files.** They are there for a reason and likely contain exactly what you need to
complete the task successfully."""
