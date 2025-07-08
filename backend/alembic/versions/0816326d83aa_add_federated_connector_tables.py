"""add federated connector tables

Revision ID: 0816326d83aa
Revises: 12635f6655b7
Create Date: 2025-06-29 14:09:45.109518

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0816326d83aa"
down_revision = "12635f6655b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create federated_connector table
    op.create_table(
        "federated_connector",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("credentials", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create federated_connector_oauth_token table
    op.create_table(
        "federated_connector_oauth_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("federated_connector_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["federated_connector_id"], ["federated_connector.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create federated_connector__document_set table
    op.create_table(
        "federated_connector__document_set",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("federated_connector_id", sa.Integer(), nullable=False),
        sa.Column("document_set_id", sa.Integer(), nullable=False),
        sa.Column("entities", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["federated_connector_id"], ["federated_connector.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_set_id"], ["document_set.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "federated_connector_id",
            "document_set_id",
            name="uq_federated_connector_document_set",
        ),
    )


def downgrade() -> None:
    # Drop tables in reverse order due to foreign key dependencies
    op.drop_table("federated_connector__document_set")
    op.drop_table("federated_connector_oauth_token")
    op.drop_table("federated_connector")
