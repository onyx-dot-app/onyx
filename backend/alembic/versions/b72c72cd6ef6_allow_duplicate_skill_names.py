"""Allow duplicate skill names.

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
    op.execute("UPDATE skill SET name = slug")
    op.alter_column(
        "skill",
        "name",
        existing_type=sa.String(),
        type_=sa.String(length=64),
        nullable=False,
    )
    op.create_index("ix_skill_name", "skill", ["name"])

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
    op.create_unique_constraint("uq_skill_id_name", "skill", ["id", "name"])
    op.drop_constraint(
        "user_skill_preference_skill_id_fkey",
        "user_skill_preference",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_user_skill_preference_skill_name",
        "user_skill_preference",
        "skill",
        ["skill_id", "name"],
        ["id", "name"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_user_skill_preference_enabled_name",
        "user_skill_preference",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.column("enabled").is_(True),
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
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM skill GROUP BY slug HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade while duplicate skill names exist';
            END IF;
        END$$
        """
    )
    op.drop_index(
        "uq_user_skill_preference_enabled_name",
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
    op.drop_constraint("uq_skill_id_name", "skill", type_="unique")
    op.drop_column("user_skill_preference", "name")
    op.drop_index("ix_skill_name", table_name="skill")
    op.alter_column(
        "skill",
        "name",
        existing_type=sa.String(length=64),
        type_=sa.String(),
        nullable=False,
    )
    op.execute(
        """
        UPDATE skill
        SET name = external_app.name
        FROM external_app
        WHERE external_app.skill_id = skill.id
        """
    )
    op.create_unique_constraint("uq_skill_slug", "skill", ["slug"])
    op.drop_column("external_app", "name")
