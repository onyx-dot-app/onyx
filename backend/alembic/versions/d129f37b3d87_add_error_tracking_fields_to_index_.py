"""add_error_tracking_fields_to_index_attempt_errors

Revision ID: d129f37b3d87
Revises: 503883791c39
Create Date: 2026-04-06 19:11:18.261800

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d129f37b3d87"
down_revision = "503883791c39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "index_attempt_errors",
        sa.Column("error_type", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_attempt_errors", "error_type")
