"""add allow_email_link to sso_provider

Revision ID: 48589afda2aa
Revises: e2875ce6454b
Create Date: 2026-07-21 12:50:50.134166

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "48589afda2aa"
down_revision = "e2875ce6454b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sso_provider",
        sa.Column(
            "allow_email_link",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("sso_provider", "allow_email_link")
