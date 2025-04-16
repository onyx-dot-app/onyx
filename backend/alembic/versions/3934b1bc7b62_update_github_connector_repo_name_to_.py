"""Update GitHub connector repo_name to repositories

Revision ID: 3934b1bc7b62
Revises: b7c2b63c4a03
Create Date: 2025-03-05 10:50:30.516962

"""

from alembic import op
import sqlalchemy as sa
import json
import logging

# revision identifiers, used by Alembic.
revision = "3934b1bc7b62"
down_revision = "b7c2b63c4a03"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    # Get all GitHub connectors
    conn = op.get_bind()

    # First get all GitHub connectors
    github_connectors = conn.execute(
        sa.text(
            """
            SELECT id, connector_specific_config
            FROM connector
            WHERE source = 'GITHUB'
            """
        )
    ).fetchall()

    # Update each connector's config
    updated_count = 0
    for connector_id, config in github_connectors:
        try:
            if not config:
                logger.warning(f"Connector {connector_id} has no config, skipping")
                continue

            # Parse the config if it's a string
            if isinstance(config, str):
                config = json.loads(config)

            if "repo_name" not in config:
                continue

            # Create new config with repositories instead of repo_name
            new_config = dict(config)
            repo_name_value = new_config.pop("repo_name")
            new_config["repositories"] = repo_name_value

            # Update the connector with the new config
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
            updated_count += 1
        except Exception as e:
            logger.error(f"Error updating connector {connector_id}: {str(e)}")


def downgrade() -> None:
    # Get all GitHub connectors
    conn = op.get_bind()

    logger.debug(
        "Starting rollback of GitHub connectors from repositories to repo_name"
    )

    github_connectors = conn.execute(
        sa.text(
            """
            SELECT id, connector_specific_config
            FROM connector
            WHERE source = 'GITHUB'
            """
        )
    ).fetchall()

    logger.debug(f"Found {len(github_connectors)} GitHub connectors to rollback")

    # Revert each GitHub connector to use repo_name instead of repositories
    reverted_count = 0
    for connector_id, config in github_connectors:
        try:
            if not config:
                continue

            # Parse the config if it's a string
            if isinstance(config, str):
                config = json.loads(config)

            if "repositories" not in config:
                continue

            # Create new config with repo_name instead of repositories
            new_config = dict(config)
            repositories_value = new_config.pop("repositories")
            new_config["repo_name"] = repositories_value

            # Update the connector with the new config
            conn.execute(
                sa.text(
                    """
                    UPDATE connector
                    SET connector_specific_config = :new_config
                    WHERE id = :connector_id
                    """
                ),
                {"new_config": json.dumps(new_config), "connector_id": connector_id},
            )
            reverted_count += 1
        except Exception as e:
            logger.error(f"Error reverting connector {connector_id}: {str(e)}")
