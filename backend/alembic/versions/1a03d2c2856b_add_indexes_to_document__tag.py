"""Add indexes to document__tag

Revision ID: 1a03d2c2856b
Revises: 9c00a2bccb83
Create Date: 2025-02-18 10:45:13.957807

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "1a03d2c2856b"
down_revision = "9c00a2bccb83"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_document__tag_tag_id"),
        "document__tag",
        ["tag_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document__tag_tag_id"), table_name="document__tag")
