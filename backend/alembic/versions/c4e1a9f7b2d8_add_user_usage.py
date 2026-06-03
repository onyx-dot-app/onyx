"""add user_usage ledger

Revision ID: c4e1a9f7b2d8
Revises: 4d545225fd82
Create Date: 2026-06-03 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy

# revision identifiers, used by Alembic.
revision = "c4e1a9f7b2d8"
down_revision = "4d545225fd82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column(
            "window_start", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("flow", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "cache_read_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cost_cents", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_usage_user_id", "user_usage", ["user_id"], unique=False)
    # Upsert key; NULLS NOT DISTINCT (PG15+) so rows with provider IS NULL
    # collide as one. Raw DDL because this SQLAlchemy version can't emit the
    # clause via op.create_index.
    op.execute(
        "CREATE UNIQUE INDEX uq_user_usage_dims ON user_usage "
        "(user_id, window_start, model, flow, provider) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    op.drop_index("uq_user_usage_dims", table_name="user_usage")
    op.drop_index("ix_user_usage_user_id", table_name="user_usage")
    op.drop_index("ix_user_usage_window_start", table_name="user_usage")
    op.drop_table("user_usage")
