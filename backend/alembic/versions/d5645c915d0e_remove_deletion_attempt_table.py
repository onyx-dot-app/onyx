"""Remove deletion_attempt table

Revision ID: d5645c915d0e
Revises: 8e26726b7683
Create Date: 2023-09-14 15:04:14.444909

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d5645c915d0e"
down_revision = "8e26726b7683"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_table("deletion_attempt")

    # Remove the DeletionStatus enum
    op.execute("DROP TYPE IF EXISTS deletionstatus;")


def downgrade() -> None:
    op.create_table(
        "deletion_attempt",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("connector_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("credential_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "NOT_STARTED",
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                name="deletionstatus",
            ),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "num_docs_deleted",
            sa.INTEGER(),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("error_msg", sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column(
            "time_created",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "time_updated",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connector.id"],
            name="deletion_attempt_connector_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
            name="deletion_attempt_credential_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="deletion_attempt_pkey"),
    )
