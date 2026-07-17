"""Per-user skill preferences.

Revision ID: b1d060254b02
Revises: 8f3b2c91d4e7
Create Date: 2026-07-16 13:47:31.228302

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b1d060254b02"
down_revision = "8f3b2c91d4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_skill_preference",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "skill_id"),
    )
    op.create_index(
        "ix_user_skill_preference_skill_id",
        "user_skill_preference",
        ["skill_id"],
    )
    # Reset custom-skill sharing for the small existing rollout. External apps
    # remain organization-visible and native built-ins retain their visibility.
    op.execute(
        """
        DELETE FROM skill__user
        WHERE skill_id IN (
          SELECT skill.id
          FROM skill
          LEFT JOIN external_app ON external_app.skill_id = skill.id
          WHERE skill.built_in_skill_id IS NULL
            AND external_app.id IS NULL
        )
        """
    )
    op.execute(
        """
        DELETE FROM skill__user_group
        WHERE skill_id IN (
          SELECT skill.id
          FROM skill
          LEFT JOIN external_app ON external_app.skill_id = skill.id
          WHERE skill.built_in_skill_id IS NULL
            AND external_app.id IS NULL
        )
        """
    )
    op.execute(
        """
        UPDATE skill
        SET public_permission = NULL
        WHERE skill.built_in_skill_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM external_app WHERE external_app.skill_id = skill.id
          )
        """
    )

    # Owners keep their custom skills enabled. Custom skills without an owner
    # remain manageable by admins but have no user preference until re-shared.
    op.execute(
        """
        INSERT INTO user_skill_preference (user_id, skill_id, enabled)
        SELECT skill.author_user_id, skill.id, true
        FROM skill
        LEFT JOIN external_app ON external_app.skill_id = skill.id
        WHERE skill.built_in_skill_id IS NULL
          AND external_app.id IS NULL
          AND skill.author_user_id IS NOT NULL
        """
    )

    op.drop_column("skill", "enabled")


def downgrade() -> None:
    # The custom-skill share reset and previous tenant-wide enabled values
    # cannot be reconstructed. Downgraded skills therefore default enabled.
    op.add_column(
        "skill",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.drop_index(
        "ix_user_skill_preference_skill_id",
        table_name="user_skill_preference",
    )
    op.drop_table("user_skill_preference")
