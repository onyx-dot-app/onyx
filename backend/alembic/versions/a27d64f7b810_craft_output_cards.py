"""Persist Craft output identities and viewed revisions.

Revision ID: a27d64f7b810
Revises: 0140c82e8a7f
"""

from alembic import op
import sqlalchemy as sa

revision = "a27d64f7b810"
down_revision = "0140c82e8a7f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifact", sa.Column("source_revision", sa.String(), nullable=True))
    op.add_column("artifact", sa.Column("viewed_revision", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("artifact", "viewed_revision")
    op.drop_column("artifact", "source_revision")
