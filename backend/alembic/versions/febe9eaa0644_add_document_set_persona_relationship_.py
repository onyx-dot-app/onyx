"""Add document_set / persona relationship table

Revision ID: febe9eaa0644
Revises: 57b53544726e
Create Date: 2023-09-24 13:06:24.018610

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "febe9eaa0644"
down_revision = "57b53544726e"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "persona__document_set",
        sa.Column("persona_id", sa.Integer(), nullable=False),
        sa.Column("document_set_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_set_id"],
            ["document_set.id"],
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("persona_id", "document_set_id"),
    )


def downgrade() -> None:
    op.drop_table("persona__document_set")
