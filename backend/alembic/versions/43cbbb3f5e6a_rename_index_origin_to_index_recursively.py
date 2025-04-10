"""Rename index_origin to index_recursively

Revision ID: 1d6ad76d1f37
Revises: e1392f05e840
Create Date: 2024-08-01 12:38:54.466081

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "1d6ad76d1f37"
down_revision = "e1392f05e840"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE connector
        SET connector_specific_config = jsonb_set(
            connector_specific_config,
            '{index_recursively}',
            'true'::jsonb
        ) - 'index_origin'
        WHERE connector_specific_config ? 'index_origin'
    """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE connector
        SET connector_specific_config = jsonb_set(
            connector_specific_config,
            '{index_origin}',
            connector_specific_config->'index_recursively'
        ) - 'index_recursively'
        WHERE connector_specific_config ? 'index_recursively'
    """
    )
