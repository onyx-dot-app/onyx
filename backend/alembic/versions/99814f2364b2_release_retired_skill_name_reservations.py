"""Release retired skill name reservations.

Revision ID: 99814f2364b2
Revises: 703815651f00
"""

from alembic import op
import sqlalchemy as sa

revision = "99814f2364b2"
down_revision = "703815651f00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE user_skill_preference SET enabled = false
        WHERE skill_id IN (SELECT id FROM skill WHERE retired_at IS NOT NULL)
    """)
    op.drop_index("uq_skill_automatic_name", table_name="skill")
    op.create_index(
        "uq_skill_automatic_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text(
            "installation_policy <> 'AVAILABLE' AND retired_at IS NULL"
        ),
    )


def downgrade() -> None:
    # Keep retired rows from conflicting with names reused after retirement.
    op.execute(
        "UPDATE skill SET installation_policy = 'AVAILABLE' WHERE retired_at IS NOT NULL"
    )
    op.execute("SET CONSTRAINTS fk_skill_current_version IMMEDIATE")
    op.drop_index("uq_skill_automatic_name", table_name="skill")
    op.create_index(
        "uq_skill_automatic_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text("installation_policy <> 'AVAILABLE'"),
    )
    op.execute("SET CONSTRAINTS fk_skill_current_version DEFERRED")
