"""cascade document set group deletion

Revision ID: 947b94d2ebf1
Revises: 34fe28843029
Create Date: 2026-09-01 16:51:10.561206

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "947b94d2ebf1"
down_revision = "34fe28843029"
branch_labels = None
depends_on = None

FK_NAME = "document_set__user_group_document_set_id_fkey"
TABLE_NAME = "document_set__user_group"
PARENT_TABLE_NAME = "document_set"


def upgrade() -> None:
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.create_foreign_key(
        FK_NAME,
        TABLE_NAME,
        PARENT_TABLE_NAME,
        ["document_set_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.create_foreign_key(
        FK_NAME,
        TABLE_NAME,
        PARENT_TABLE_NAME,
        ["document_set_id"],
        ["id"],
    )
