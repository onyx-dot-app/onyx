"""user chat defaults

Revision ID: 66a70ddc0652
Revises: e7c00417d1e5
Create Date: 2026-08-25 14:00:35.813051

"""

from alembic import op
import sqlalchemy as sa

from onyx.llm.models import ReasoningEffort

# revision identifiers, used by Alembic.
revision = "66a70ddc0652"
down_revision = "e7c00417d1e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("temperature_default", sa.Float(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column(
            "reasoning_effort_default",
            sa.Enum(
                ReasoningEffort,
                native_enum=False,
                values_callable=lambda x: [e.value for e in x],
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user", "reasoning_effort_default")
    op.drop_column("user", "temperature_default")
