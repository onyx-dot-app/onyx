"""add file names to file connector config

Revision ID: 62c3a055a141
Revises: 3fc5d75723b3
Create Date: 2025-07-30 17:01:24.417551

"""

from alembic import op
import sqlalchemy as sa
import json
import os
import logging


# revision identifiers, used by Alembic.
revision = "62c3a055a141"
down_revision = "3fc5d75723b3"
branch_labels = None
depends_on = None

SKIP_FILE_NAME_MIGRATION = (
    os.environ.get("SKIP_FILE_NAME_MIGRATION", "true").lower() == "true"
)

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    if SKIP_FILE_NAME_MIGRATION:
        logger.info(
            "Skipping file name migration. Hint: set SKIP_FILE_NAME_MIGRATION=false to run this migration"
        )
        return
    logger.info("Running file name migration")
    # Get connection
    conn = op.get_bind()

    # Get all FILE connectors with their configs
    file_connectors = conn.execute(
        sa.text(
            """
            SELECT id, connector_specific_config
            FROM connector
            WHERE source = 'FILE'
        """
        )
    ).fetchall()

    for connector_id, config in file_connectors:
        # Parse config if it's a string
        if isinstance(config, str):
            config = json.loads(config)

        # Get file_locations list
        file_locations = config.get("file_locations", [])

        # Get display names for each file_id
        file_names = []
        for file_id in file_locations:
            result = conn.execute(
                sa.text(
                    """
                    SELECT display_name
                    FROM file_record
                    WHERE file_id = :file_id
                """
                ),
                {"file_id": file_id},
            ).fetchone()

            if result:
                file_names.append(result[0])
            else:
                file_names.append(file_id)  # Should not happen

        # Add file_names to config
        new_config = dict(config)
        new_config["file_names"] = file_names

        # Update the connector
        conn.execute(
            sa.text(
                """
                UPDATE connector
                SET connector_specific_config = :new_config
                WHERE id = :connector_id
            """
            ),
            {"connector_id": connector_id, "new_config": json.dumps(new_config)},
        )


def downgrade() -> None:
    # Get connection
    conn = op.get_bind()

    # Remove file_names from all FILE connectors
    file_connectors = conn.execute(
        sa.text(
            """
            SELECT id, connector_specific_config
            FROM connector
            WHERE source = 'FILE'
        """
        )
    ).fetchall()

    for connector_id, config in file_connectors:
        # Parse config if it's a string
        if isinstance(config, str):
            config = json.loads(config)

        # Remove file_names if it exists
        if "file_names" in config:
            new_config = dict(config)
            del new_config["file_names"]

            # Update the connector
            conn.execute(
                sa.text(
                    """
                    UPDATE connector
                    SET connector_specific_config = :new_config
                    WHERE id = :connector_id
                """
                ),
                {
                    "connector_id": connector_id,
                    "new_config": json.dumps(new_config),
                },
            )
