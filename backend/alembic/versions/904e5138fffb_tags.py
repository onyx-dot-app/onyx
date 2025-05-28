"""Tags

Revision ID: 904e5138fffb
Revises: 891cd83c87a8
Create Date: 2024-01-01 10:44:43.733974

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "904e5138fffb"
down_revision = "891cd83c87a8"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tag_key", sa.String(), nullable=False),
        sa.Column("tag_value", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tag_key", "tag_value", "source", name="_tag_key_value_source_uc"
        ),
    )
    op.create_table(
        "document__tag",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tag.id"],
        ),
        sa.PrimaryKeyConstraint("document_id", "tag_id"),
    )

    op.add_column(
        "search_doc",
        sa.Column(
            "doc_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.execute("UPDATE search_doc SET doc_metadata = '{}' WHERE doc_metadata IS NULL")
    op.alter_column("search_doc", "doc_metadata", nullable=False)


def downgrade() -> None:
    op.drop_table("document__tag")
    op.drop_table("tag")
    op.drop_column("search_doc", "doc_metadata")
