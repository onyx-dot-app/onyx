"""fix_capitalization

Revision ID: be2ab2aa50ee
Revises: 369644546676
Create Date: 2025-01-10 13:13:26.228960

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "be2ab2aa50ee"
down_revision = "369644546676"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE document
        SET
            external_user_group_ids = ARRAY(
                SELECT LOWER(unnest(external_user_group_ids))
            ),
            last_modified = NOW()
        WHERE
            external_user_group_ids IS NOT NULL
            AND external_user_group_ids::text[] <> ARRAY(
                SELECT LOWER(unnest(external_user_group_ids))
            )::text[]
    """
    )


def downgrade() -> None:
    # No way to cleanly persist the bad state through an upgrade/downgrade
    # cycle, so we just pass
    pass
