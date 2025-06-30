"""add_user_id_to_federated_oauth_token

Revision ID: 5a0486c4b09b
Revises: 0816326d83aa
Create Date: 2025-06-29 17:34:43.419856

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "5a0486c4b09b"
down_revision = "0816326d83aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add user_id column to federated_connector_oauth_token table
    op.add_column(
        "federated_connector_oauth_token",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    )

    # Add foreign key constraint
    op.create_foreign_key(
        "federated_connector_oauth_token_user_id_fkey",
        "federated_connector_oauth_token",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop foreign key constraint
    op.drop_constraint(
        "federated_connector_oauth_token_user_id_fkey",
        "federated_connector_oauth_token",
        type_="foreignkey",
    )

    # Drop user_id column
    op.drop_column("federated_connector_oauth_token", "user_id")
