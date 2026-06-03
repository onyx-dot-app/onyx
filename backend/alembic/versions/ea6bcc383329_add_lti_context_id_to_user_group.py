"""add lti_context_id to user_group

Revision ID: ea6bcc383329
Revises: 503883791c39
Create Date: 2026-06-02 18:01:11.844931

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ea6bcc383329"
down_revision = "503883791c39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_group",
        sa.Column("lti_context_id", sa.String(), nullable=True),
    )
    op.add_column(
        "user_group",
        sa.Column("lti_nrps_url", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_user_group_lti_context_id"),
        "user_group",
        ["lti_context_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_group_lti_context_id"), table_name="user_group")
    op.drop_column("user_group", "lti_nrps_url")
    op.drop_column("user_group", "lti_context_id")
