"""add config to federated_connector

Revision ID: 9drpiiw74ljy
Revises: 2acdef638fc2
Create Date: 2025-11-03 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9drpiiw74ljy"
down_revision = "2acdef638fc2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # Check if column already exists in current schema
    result = connection.execute(
        sa.text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
            AND table_name = 'federated_connector'
            AND column_name = 'config'
            """
        )
    )
    column_exists = result.fetchone() is not None

    # Add config column with default empty object (only if it doesn't exist)
    if not column_exists:
        op.add_column(
            "federated_connector",
            sa.Column(
                "config", postgresql.JSONB(), nullable=False, server_default="{}"
            ),
        )

    # Data migration: Single bulk update for all Slack connectors
    connection.execute(
        sa.text(
            """
            WITH connector_configs AS (
                SELECT
                    fc.id as connector_id,
                    CASE
                        WHEN fcds.entities->'channels' IS NOT NULL
                            AND jsonb_typeof(fcds.entities->'channels') = 'array'
                            AND jsonb_array_length(fcds.entities->'channels') > 0
                        THEN
                            jsonb_build_object(
                                'channels', fcds.entities->'channels',
                                'search_all_channels', false
                            ) ||
                            CASE
                                WHEN fcds.entities->'include_dm' IS NOT NULL
                                THEN jsonb_build_object('include_dm', fcds.entities->'include_dm')
                                ELSE '{}'::jsonb
                            END
                        ELSE
                            jsonb_build_object('search_all_channels', true) ||
                            CASE
                                WHEN fcds.entities->'include_dm' IS NOT NULL
                                THEN jsonb_build_object('include_dm', fcds.entities->'include_dm')
                                ELSE '{}'::jsonb
                            END
                    END as config
                FROM federated_connector fc
                LEFT JOIN LATERAL (
                    SELECT entities
                    FROM federated_connector__document_set
                    WHERE federated_connector_id = fc.id
                    AND entities IS NOT NULL
                    ORDER BY id
                    LIMIT 1
                ) fcds ON true
                WHERE fc.source = 'FEDERATED_SLACK'
                AND fcds.entities IS NOT NULL
            )
            UPDATE federated_connector fc
            SET config = cc.config
            FROM connector_configs cc
            WHERE fc.id = cc.connector_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("federated_connector", "config")
