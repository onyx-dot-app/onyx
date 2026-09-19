"""add per model llm settings

Revision ID: dd55634b8532
Revises: 4d93b0fd5ca8
Create Date: 2026-08-18 17:15:03.559998

"""

from alembic import op
import sqlalchemy as sa

revision = "dd55634b8532"
down_revision = "4d93b0fd5ca8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unbounded VARCHAR, as reasoning_effort_override on chat_session already
    # does, so adding an effort level stays a code change.
    op.add_column(
        "model_configuration",
        sa.Column("reasoning_effort_max", sa.String(), nullable=True),
    )
    op.add_column(
        "model_configuration",
        sa.Column("reasoning_effort_default", sa.String(), nullable=True),
    )
    op.add_column(
        "model_configuration",
        sa.Column("temperature_default", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_configuration", "temperature_default")
    op.drop_column("model_configuration", "reasoning_effort_default")
    op.drop_column("model_configuration", "reasoning_effort_max")
