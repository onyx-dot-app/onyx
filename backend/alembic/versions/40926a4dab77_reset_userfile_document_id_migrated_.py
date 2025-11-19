"""reset userfile document_id_migrated field

Revision ID: 40926a4dab77
Revises: 64bd5677aeb6
Create Date: 2025-10-06 16:10:32.898668

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "40926a4dab77"
down_revision = "64bd5677aeb6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set all existing records to not migrated
    op.execute(
        "UPDATE user_file SET document_id_migrated = FALSE "
        "WHERE document_id_migrated IS DISTINCT FROM FALSE;"
    )


def downgrade() -> None:
    # No-op
    pass
