"""add skill installation policies

Revision ID: 4d8453213439
Revises: 131ed5e307a4
Create Date: 2026-10-20 12:09:09.654629

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4d8453213439"
down_revision = "131ed5e307a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Match the active human admin filter in db.users._active_admin_user_stmt.
    op.execute(
        """
        WITH successor AS (
            SELECT id FROM "user"
            WHERE is_active IS TRUE
              AND effective_permissions @> '["admin"]'::jsonb
              AND email NOT LIKE '%onyxapikey.ai'
              AND email NOT IN ('anonymous@onyx.app', 'no-auth-placeholder@onyx.app')
            ORDER BY id
            LIMIT 1
        )
        UPDATE skill SET author_user_id = successor.id
        FROM successor
        WHERE skill.author_user_id IS NULL AND skill.built_in_skill_id IS NULL
          AND skill.public_permission IS NULL
        """
    )
    op.create_check_constraint(
        "ck_private_skill_has_owner",
        "skill",
        "built_in_skill_id IS NOT NULL OR public_permission IS NOT NULL OR author_user_id IS NOT NULL",
    )
    op.add_column(
        "skill",
        sa.Column(
            "installation_policy",
            sa.String(),
            nullable=False,
            server_default="AVAILABLE",
        ),
    )
    op.create_index(
        "uq_skill_automatic_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text("installation_policy <> 'AVAILABLE'"),
    )
    op.add_column(
        "user_skill_preference",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_index("uq_user_skill_preference_name", table_name="user_skill_preference")
    op.create_index(
        "uq_user_skill_preference_name",
        "user_skill_preference",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("enabled"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_private_skill_has_owner", "skill", type_="check")
    op.execute("DELETE FROM user_skill_preference WHERE NOT enabled")
    op.drop_index("uq_user_skill_preference_name", table_name="user_skill_preference")
    op.create_index(
        "uq_user_skill_preference_name",
        "user_skill_preference",
        ["user_id", "name"],
        unique=True,
    )
    op.drop_column("user_skill_preference", "enabled")
    op.drop_index("uq_skill_automatic_name", table_name="skill")
    op.drop_column("skill", "installation_policy")
