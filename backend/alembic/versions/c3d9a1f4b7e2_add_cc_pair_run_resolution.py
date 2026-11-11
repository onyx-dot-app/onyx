"""Record which failed runs of a pair an admin resolved.

Revision ID: c3d9a1f4b7e2
Revises: c82f4a0e3d15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d9a1f4b7e2"
down_revision = "c82f4a0e3d15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cc_pair_run_resolution",
        # A run id is unique only within its kind's table.
        sa.Column("run_kind", sa.String(), primary_key=True),
        sa.Column("attempt_id", sa.Integer(), primary_key=True),
        sa.Column(
            "cc_pair_id",
            sa.Integer(),
            sa.ForeignKey("connector_credential_pair.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("cc_pair_run_resolution")
