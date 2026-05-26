"""Create action_approval table

Revision ID: 366c05b6f485
Revises: c7bc8cc2921d
Create Date: 2026-05-21 09:30:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "366c05b6f485"
down_revision = "c7bc8cc2921d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_approval",
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "APPROVED",
                "REJECTED",
                "EXPIRED",
                name="approvaldecision",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["build_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )


def downgrade() -> None:
    op.drop_table("action_approval")
