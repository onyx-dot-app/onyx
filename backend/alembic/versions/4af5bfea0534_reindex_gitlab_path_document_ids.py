"""Reindex GitLab documents with stable path IDs.

Revision ID: 4af5bfea0534
Revises: c7d1f0a4b8e2
Create Date: 2026-07-16 19:01:29.535419
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4af5bfea0534"
down_revision = "c7d1f0a4b8e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "reindex_required_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "index_attempt",
        sa.Column(
            "reindex_requirement_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE connector
        SET connector_specific_config = jsonb_set(
            connector_specific_config - 'clone_depth',
            '{archive_sync_version}',
            '1'::jsonb
        )
        WHERE source = 'GITLAB'
        """
    )
    op.execute(
        """
        UPDATE connector_credential_pair
        SET indexing_trigger = 'REINDEX',
            reindex_required_since = clock_timestamp()
        WHERE connector_id IN (
            SELECT id
            FROM connector
            WHERE source = 'GITLAB'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE connector
        SET connector_specific_config = jsonb_set(
            connector_specific_config - 'archive_sync_version',
            '{clone_depth}',
            '1'::jsonb
        )
        WHERE source = 'GITLAB'
        """
    )
    op.drop_column("index_attempt", "reindex_requirement_started_at")
    op.drop_column("connector_credential_pair", "reindex_required_since")
