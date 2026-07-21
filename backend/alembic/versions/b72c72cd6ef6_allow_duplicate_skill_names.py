"""Allow duplicate skill names.

Before this migration, ``Skill.slug`` was the unique canonical Agent Skills
name, while ``Skill.name`` also held editable display metadata. External apps
stored their display names on the linked skill, and user preferences identified
skills by ``(user_id, skill_id)`` plus an ``enabled`` boolean.

After the upgrade, ``Skill.name`` is the sole canonical skill name and may be
shared by multiple skill rows. External-app display names live independently on
``ExternalApp.name``. ``UserSkillPreference.name`` mirrors the referenced skill
name through a composite foreign key. A preference row now means the skill is
enabled, and a unique index enforces at most one selection per ``(user_id,
name)`` while preserving UUID-based skill identity.

Revision ID: b72c72cd6ef6
Revises: eec4fc85ef28
Create Date: 2026-07-20 16:32:40.354227

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b72c72cd6ef6"
down_revision = "eec4fc85ef28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_app",
        sa.Column("name", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE external_app
        SET name = skill.name
        FROM skill
        WHERE skill.id = external_app.skill_id
        """
    )
    op.alter_column(
        "external_app",
        "name",
        existing_type=sa.String(),
        nullable=False,
    )

    op.drop_constraint("uq_skill_slug", "skill", type_="unique")
    op.alter_column(
        "skill",
        "name",
        existing_type=sa.String(),
        type_=sa.String(length=64),
        postgresql_using="slug",
    )

    op.add_column(
        "user_skill_preference",
        sa.Column("name", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE user_skill_preference
        SET name = skill.name
        FROM skill
        WHERE skill.id = user_skill_preference.skill_id
        """
    )
    op.alter_column(
        "user_skill_preference",
        "name",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_unique_constraint("uq_skill_name_id", "skill", ["name", "id"])
    op.drop_constraint(
        "user_skill_preference_skill_id_fkey",
        "user_skill_preference",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_user_skill_preference_skill_name",
        "user_skill_preference",
        "skill",
        ["name", "skill_id"],
        ["name", "id"],
        ondelete="CASCADE",
    )
    op.execute("DELETE FROM user_skill_preference WHERE NOT enabled")
    op.drop_column("user_skill_preference", "enabled")
    op.create_index(
        "uq_user_skill_preference_name",
        "user_skill_preference",
        ["user_id", "name"],
        unique=True,
    )
    op.drop_column("skill", "slug")


def downgrade() -> None:
    op.add_column(
        "skill",
        sa.Column("slug", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE skill SET slug = name")
    op.alter_column(
        "skill",
        "slug",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_unique_constraint("uq_skill_slug", "skill", ["slug"])
    op.drop_index(
        "uq_user_skill_preference_name",
        table_name="user_skill_preference",
    )
    op.drop_constraint(
        "fk_user_skill_preference_skill_name",
        "user_skill_preference",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_skill_preference_skill_id_fkey",
        "user_skill_preference",
        "skill",
        ["skill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_skill_name_id", "skill", type_="unique")
    op.add_column(
        "user_skill_preference",
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.alter_column("user_skill_preference", "enabled", server_default=None)
    op.drop_column("user_skill_preference", "name")
    op.alter_column(
        "skill",
        "name",
        existing_type=sa.String(length=64),
        type_=sa.String(),
    )
    op.execute(
        """
        UPDATE skill
        SET name = external_app.name
        FROM external_app
        WHERE external_app.skill_id = skill.id
        """
    )
    op.drop_column("external_app", "name")
