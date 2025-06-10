"""add index to index_attempt.time_created

Revision ID: 0f7ff6d75b57
Revises: 369644546676
Create Date: 2025-01-10 14:01:14.067144

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0f7ff6d75b57"
down_revision = "fec3db967bf7"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_index_attempt_status"),
        "index_attempt",
        ["status"],
        unique=False,
    )

    op.create_index(
        op.f("ix_index_attempt_time_created"),
        "index_attempt",
        ["time_created"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_index_attempt_time_created"), table_name="index_attempt")

    op.drop_index(op.f("ix_index_attempt_status"), table_name="index_attempt")
