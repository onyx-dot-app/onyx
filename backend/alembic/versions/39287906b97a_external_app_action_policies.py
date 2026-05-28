"""external app action policies

Revision ID: 39287906b97a
Revises: 366c05b6f485
Create Date: 2026-05-26 12:01:05.260678

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "39287906b97a"
down_revision = "366c05b6f485"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_app_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_app_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("policy", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["external_app_id"], ["external_app.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_app_id",
            "action_id",
            name="uq_external_app_policy_app_action",
        ),
    )


def downgrade() -> None:
    op.drop_table("external_app_policy")
