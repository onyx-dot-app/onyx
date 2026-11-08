"""add skill marketplaces

Revision ID: 1c894e757414
Revises: 13a2d6969b0b
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "1c894e757414"
down_revision = "13a2d6969b0b"
branch_labels = None
depends_on = None


_PRIVATE_OWNER_CHECK = "built_in_skill_id IS NOT NULL OR public_permission IS NOT NULL OR author_user_id IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "marketplace",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "login_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
        ),
        sa.Column("last_synced_revision", sa.String()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("webhook_id", sa.String()),
        sa.Column("webhook_secret", sa.LargeBinary()),
    )
    op.create_table(
        "marketplace__user_group",
        sa.Column(
            "marketplace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("marketplace.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", sa.String(), nullable=False, server_default="VIEWER"),
        sa.Column("installation_policy", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_marketplace__user_group_user_group_id",
        "marketplace__user_group",
        ["user_group_id"],
    )
    op.add_column("skill", sa.Column("marketplace_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_skill_marketplace",
        "skill",
        "marketplace",
        ["marketplace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_skill_marketplace_id", "skill", ["marketplace_id"])
    op.add_column("skill", sa.Column("marketplace_entry_key", sa.String()))
    op.create_check_constraint(
        "ck_skill_marketplace_entry_key",
        "skill",
        "marketplace_id IS NULL OR marketplace_entry_key IS NOT NULL",
    )
    op.add_column(
        "skill",
        sa.Column(
            "follows_marketplace_access",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("skill", sa.Column("retired_at", sa.DateTime(timezone=True)))
    op.create_index(
        "uq_skill_live_marketplace_entry",
        "skill",
        ["marketplace_id", "marketplace_entry_key"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    op.drop_constraint("ck_private_skill_has_owner", "skill", type_="check")
    op.create_check_constraint(
        "ck_private_skill_has_owner",
        "skill",
        _PRIVATE_OWNER_CHECK + " OR marketplace_id IS NOT NULL",
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM skill WHERE "
            "(marketplace_id IS NOT NULL AND author_user_id IS NULL) OR retired_at IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Cannot downgrade while ownerless marketplace skills or retired skills exist. "
            "Remove retired skills and assign owners to remaining marketplace skills first."
        )
    op.drop_constraint("ck_private_skill_has_owner", "skill", type_="check")
    op.create_check_constraint(
        "ck_private_skill_has_owner", "skill", _PRIVATE_OWNER_CHECK
    )
    op.drop_constraint("ck_skill_marketplace_entry_key", "skill", type_="check")
    op.drop_index("uq_skill_live_marketplace_entry", table_name="skill")
    op.drop_index("ix_skill_marketplace_id", table_name="skill")
    op.drop_constraint("fk_skill_marketplace", "skill", type_="foreignkey")
    for column in (
        "retired_at",
        "follows_marketplace_access",
        "marketplace_entry_key",
        "marketplace_id",
    ):
        op.drop_column("skill", column)
    op.drop_table("marketplace__user_group")
    op.drop_table("marketplace")
