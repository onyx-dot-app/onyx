"""add full_exception_trace to permission sync attempts

Revision ID: 1c36b3dc2f4e
Revises: f0db5f1c6370
Create Date: 2026-05-06 16:18:40.855449

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1c36b3dc2f4e"
down_revision = "f0db5f1c6370"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "doc_permission_sync_attempt",
        sa.Column("full_exception_trace", sa.Text(), nullable=True),
    )
    op.add_column(
        "external_group_permission_sync_attempt",
        sa.Column("full_exception_trace", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("external_group_permission_sync_attempt", "full_exception_trace")
    op.drop_column("doc_permission_sync_attempt", "full_exception_trace")
