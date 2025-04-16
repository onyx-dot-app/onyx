"""Add models-configuration table

Revision ID: 7a70b7664e37
Revises: cf90764725d8
Create Date: 2025-04-10 15:00:35.984669

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7a70b7664e37"
down_revision = "d961aca62eb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("llm_provider_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_visible", sa.Boolean(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["llm_provider_id"], ["llm_provider.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("llm_provider_id", "name"),
    )
    op.drop_column("llm_provider", "model_names")
    op.drop_column("llm_provider", "display_model_names")


def downgrade() -> None:
    op.drop_table("model_configuration")
    op.add_column(
        "llm_provider",
        sa.Column(
            "model_names",
            postgresql.ARRAY(sa.VARCHAR()),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "llm_provider",
        sa.Column(
            "display_model_names",
            postgresql.ARRAY(sa.VARCHAR()),
            autoincrement=False,
            nullable=True,
        ),
    )
