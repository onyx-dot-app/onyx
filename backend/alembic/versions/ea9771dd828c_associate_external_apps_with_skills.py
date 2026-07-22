"""Associate external apps with skills.

Revision ID: ea9771dd828c
Revises: f0ff4d3e69ac
Create Date: 2026-07-22 11:47:14.521933

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "ea9771dd828c"
down_revision = "f0ff4d3e69ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_app__skill",
        sa.Column("external_app_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["external_app_id"], ["external_app.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("external_app_id", "skill_id"),
        sa.UniqueConstraint("skill_id", name="uq_external_app__skill_skill_id"),
    )
    op.execute(
        """
        INSERT INTO external_app__skill (external_app_id, skill_id)
        SELECT id, skill_id
        FROM external_app
        """
    )
    op.drop_column("external_app", "skill_id")


def downgrade() -> None:
    has_non_representable_apps = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT EXISTS (
                SELECT 1
                FROM external_app
                LEFT JOIN external_app__skill
                    ON external_app__skill.external_app_id = external_app.id
                GROUP BY external_app.id
                HAVING COUNT(external_app__skill.skill_id) <> 1
            )
            """
            )
        )
        .scalar_one()
    )
    if has_non_representable_apps:
        raise RuntimeError(
            "Cannot downgrade while an external app has zero or multiple "
            "associated skills; the previous schema requires exactly one."
        )

    op.add_column(
        "external_app",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE external_app
        SET skill_id = association.skill_id
        FROM (
            SELECT DISTINCT ON (external_app_id) external_app_id, skill_id
            FROM external_app__skill
            ORDER BY external_app_id, skill_id
        ) AS association
        WHERE external_app.id = association.external_app_id
        """
    )
    op.alter_column("external_app", "skill_id", nullable=False)
    op.create_foreign_key(
        "external_app_skill_id_fkey",
        "external_app",
        "skill",
        ["skill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_external_app_skill_id", "external_app", ["skill_id"]
    )
    op.drop_table("external_app__skill")
