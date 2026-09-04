"""add system llm usage

Revision ID: ad99acb9be41
Revises: 947b94d2ebf1
Create Date: 2026-09-02 16:59:23.117473

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ad99acb9be41"
down_revision = "947b94d2ebf1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_usage",
        sa.Column("actor_kind", sa.String(), server_default="USER", nullable=False),
    )
    op.add_column(
        "user_usage",
        sa.Column("system_attribution", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        "ck_user_usage_actor",
        "user_usage",
        "(actor_kind = 'USER' AND system_attribution IS NULL) OR "
        "(actor_kind = 'SYSTEM' AND user_id IS NULL "
        "AND system_attribution IS NOT NULL AND incognito = false)",
    )
    op.drop_index("uq_user_usage_dims", table_name="user_usage")
    op.create_index(
        "uq_user_usage_dims",
        "user_usage",
        ["user_id", "window_start", "model", "flow", "provider", "incognito"],
        unique=True,
        postgresql_where=sa.text("actor_kind = 'USER'"),
    )
    op.create_index(
        "uq_system_usage_dims",
        "user_usage",
        ["system_attribution", "window_start", "model", "flow", "provider"],
        unique=True,
        postgresql_where=sa.text("actor_kind = 'SYSTEM'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_usage WHERE actor_kind = 'SYSTEM'")
    op.drop_index("uq_system_usage_dims", table_name="user_usage")
    op.drop_index("uq_user_usage_dims", table_name="user_usage")
    op.create_index(
        "uq_user_usage_dims",
        "user_usage",
        ["user_id", "window_start", "model", "flow", "provider", "incognito"],
        unique=True,
    )
    op.drop_constraint("ck_user_usage_actor", "user_usage", type_="check")
    op.drop_column("user_usage", "system_attribution")
    op.drop_column("user_usage", "actor_kind")
