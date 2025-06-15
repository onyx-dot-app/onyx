"""migrate jira connectors to new format

Revision ID: da42808081e3
Revises: f13db29f3101
Create Date: 2025-02-24 11:24:54.396040

"""

from alembic import op
import sqlalchemy as sa
import json

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.utils import extract_jira_project


# revision identifiers, used by Alembic.
revision = "da42808081e3"
down_revision = "f13db29f3101"
branch_labels = None
depends_on = None


PRESERVED_CONFIG_KEYS = ["comment_email_blacklist", "batch_size", "labels_to_skip"]


def upgrade() -> None:
    # Get all Jira connectors
    conn = op.get_bind()

    # First get all Jira connectors
    jira_connectors = conn.execute(
        sa.text(
            """
            SELECT id, connector_specific_config
            FROM connector
            WHERE source = :source
            """
        ),
        {"source": DocumentSource.JIRA.value.upper()},
    ).fetchall()

    # Update each connector's config
    for connector_id, old_config in jira_connectors:
        if not old_config:
            continue

        # Extract project key from URL if it exists
        new_config: dict[str, str | None] = {}
        if project_url := old_config.get("jira_project_url"):
            # Parse the URL to get base and project
            try:
                jira_base, project_key = extract_jira_project(project_url)
                new_config = {"jira_base_url": jira_base, "project_key": project_key}
            except ValueError:
                # If URL parsing fails, just use the URL as the base
                new_config = {
                    "jira_base_url": project_url.split("/projects/")[0],
                    "project_key": None,
                }
        else:
            # For connectors without a project URL, we need admin intervention
            # Mark these for review
            print(
                f"WARNING: Jira connector {connector_id} has no project URL configured"
            )
            continue
        for old_key in PRESERVED_CONFIG_KEYS:
            if old_key in old_config:
                new_config[old_key] = old_config[old_key]

        # Update the connector config
        conn.execute(
            sa.text(
                """
                UPDATE connector
                SET connector_specific_config = :new_config
                WHERE id = :id
                """
            ),
            {"id": connector_id, "new_config": json.dumps(new_config)},
        )


def downgrade() -> None:
    # Get all Jira connectors
    conn = op.get_bind()

    # First get all Jira connectors
    jira_connectors = conn.execute(
        sa.text(
            """
            SELECT id, connector_specific_config
            FROM connector
            WHERE source = :source
            """
        ),
        {"source": DocumentSource.JIRA.value.upper()},
    ).fetchall()

    # Update each connector's config back to the old format
    for connector_id, new_config in jira_connectors:
        if not new_config:
            continue

        old_config = {}
        base_url = new_config.get("jira_base_url")
        project_key = new_config.get("project_key")

        if base_url and project_key:
            old_config = {"jira_project_url": f"{base_url}/projects/{project_key}"}
        elif base_url:
            old_config = {"jira_project_url": base_url}
        else:
            continue

        for old_key in PRESERVED_CONFIG_KEYS:
            if old_key in new_config:
                old_config[old_key] = new_config[old_key]

        # Update the connector config
        conn.execute(
            sa.text(
                """
                UPDATE connector
                SET connector_specific_config = :old_config
                WHERE id = :id
                """
            ),
            {"id": connector_id, "old_config": json.dumps(old_config)},
        )
