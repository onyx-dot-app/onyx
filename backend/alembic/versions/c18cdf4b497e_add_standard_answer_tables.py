"""Add standard_answer tables

Revision ID: c18cdf4b497e
Revises: 3a7802814195
Create Date: 2024-06-06 15:15:02.000648

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c18cdf4b497e"
down_revision = "3a7802814195"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "standard_answer",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(), nullable=False),
        sa.Column("answer", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("keyword"),
    )
    op.create_table(
        "standard_answer_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "standard_answer__standard_answer_category",
        sa.Column("standard_answer_id", sa.Integer(), nullable=False),
        sa.Column("standard_answer_category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["standard_answer_category_id"],
            ["standard_answer_category.id"],
        ),
        sa.ForeignKeyConstraint(
            ["standard_answer_id"],
            ["standard_answer.id"],
        ),
        sa.PrimaryKeyConstraint("standard_answer_id", "standard_answer_category_id"),
    )
    op.create_table(
        "slack_bot_config__standard_answer_category",
        sa.Column("slack_bot_config_id", sa.Integer(), nullable=False),
        sa.Column("standard_answer_category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["slack_bot_config_id"],
            ["slack_bot_config.id"],
        ),
        sa.ForeignKeyConstraint(
            ["standard_answer_category_id"],
            ["standard_answer_category.id"],
        ),
        sa.PrimaryKeyConstraint("slack_bot_config_id", "standard_answer_category_id"),
    )

    op.add_column(
        "chat_session", sa.Column("slack_thread_id", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_session", "slack_thread_id")

    op.drop_table("slack_bot_config__standard_answer_category")
    op.drop_table("standard_answer__standard_answer_category")
    op.drop_table("standard_answer_category")
    op.drop_table("standard_answer")
