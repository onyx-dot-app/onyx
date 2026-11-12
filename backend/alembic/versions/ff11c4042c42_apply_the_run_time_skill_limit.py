"""apply the run-time skill limit

Drop uq_skill_automatic_name: the run-time name order now decides which of
two same-name skills a user gets. Add sandbox.skill_omissions: the plugins the
run-time skill limit left out of the content a sandbox got.

Revision ID: ff11c4042c42
Revises: 26ff9e3664f0
Create Date: 2026-11-12 11:19:14.960270

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ff11c4042c42"
down_revision = "26ff9e3664f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_skill_automatic_name", table_name="skill")
    op.add_column(
        "sandbox",
        sa.Column(
            "skill_omissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sandbox", "skill_omissions")
    # The legacy column is a mirror; the plugin tables keep the real setting.
    # Keep the oldest automatic row of each name so the index can come back.
    op.execute(
        """
        UPDATE skill SET installation_policy = 'AVAILABLE'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY name ORDER BY created_at, id
                ) AS position
                FROM skill
                WHERE installation_policy <> 'AVAILABLE'
            ) AS ranked
            WHERE position > 1
        )
        """
    )
    op.create_index(
        "uq_skill_automatic_name",
        "skill",
        ["name"],
        unique=True,
        postgresql_where=sa.text("installation_policy <> 'AVAILABLE'"),
    )
