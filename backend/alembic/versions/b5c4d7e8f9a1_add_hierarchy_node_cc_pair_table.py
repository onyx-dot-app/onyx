"""add hierarchy_node_by_connector_credential_pair table

Revision ID: b5c4d7e8f9a1
Revises: a3b8d9e2f1c4
Create Date: 2026-03-04

"""

import sqlalchemy as sa
from alembic import op

revision = "b5c4d7e8f9a1"
down_revision = "a3b8d9e2f1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hierarchy_node_by_connector_credential_pair",
        sa.Column("hierarchy_node_id", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hierarchy_node_id"],
            ["hierarchy_node.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connector.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("hierarchy_node_id", "connector_id", "credential_id"),
    )
    op.create_index(
        "ix_hierarchy_node_cc_pair_connector_credential",
        "hierarchy_node_by_connector_credential_pair",
        ["connector_id", "credential_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hierarchy_node_cc_pair_connector_credential",
        table_name="hierarchy_node_by_connector_credential_pair",
    )
    op.drop_table("hierarchy_node_by_connector_credential_pair")
