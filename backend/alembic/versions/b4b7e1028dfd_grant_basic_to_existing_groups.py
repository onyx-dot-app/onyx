"""grant_basic_to_existing_groups

Grants the "basic" permission to all existing non-default groups that
don't already have it. Every group should have at least "basic" so that
its members get basic access when effective_permissions is backfilled.

Revision ID: b4b7e1028dfd
Revises: b7bcc991d722
Create Date: 2026-03-30 16:15:17.093498

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b4b7e1028dfd"
down_revision = "b7bcc991d722"
branch_labels: str | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO permission_grant (group_id, permission, grant_source, is_deleted)
            SELECT g.id, 'basic', 'SYSTEM', false
            FROM user_group g
            WHERE g.is_default = false
              AND NOT EXISTS (
                  SELECT 1 FROM permission_grant pg
                  WHERE pg.group_id = g.id
                    AND pg.permission = 'basic'
              )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            DELETE FROM permission_grant
            WHERE permission = 'basic'
              AND grant_source = 'SYSTEM'
              AND group_id IN (
                  SELECT id FROM user_group WHERE is_default = false
              )
            """
        )
    )
