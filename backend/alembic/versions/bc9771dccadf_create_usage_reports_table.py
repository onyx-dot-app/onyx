"""create usage reports table

Revision ID: bc9771dccadf
Revises: 0568ccf46a6b
Create Date: 2024-06-18 10:04:26.800282

"""

from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy

# revision identifiers, used by Alembic.
revision = "bc9771dccadf"
down_revision = "0568ccf46a6b"

branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "usage_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_name", sa.String(), nullable=False),
        sa.Column(
            "requestor_user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_to", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_name"],
            ["file_store.file_name"],
        ),
        sa.ForeignKeyConstraint(
            ["requestor_user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("usage_reports")
