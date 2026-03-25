"""rename persona is_visible to is_listed and featured to is_featured

Revision ID: b728689f45b1
Revises: 689433b0d8de
Create Date: 2026-03-23 12:36:26.607305

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b728689f45b1"
down_revision = "689433b0d8de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("persona", "is_visible", new_column_name="is_listed")
    op.alter_column("persona", "featured", new_column_name="is_featured")


def downgrade() -> None:
    op.alter_column("persona", "is_listed", new_column_name="is_visible")
    op.alter_column("persona", "is_featured", new_column_name="featured")
