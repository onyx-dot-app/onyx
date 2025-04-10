"""add last_pruned to the connector_credential_pair table

Revision ID: ac5eaac849f9
Revises: 52a219fb5233
Create Date: 2024-09-10 15:04:26.437118

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ac5eaac849f9"
down_revision = "46b7a812670f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # last pruned represents the last time the connector was pruned
    op.add_column(
        "connector_credential_pair",
        sa.Column("last_pruned", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "last_pruned")
