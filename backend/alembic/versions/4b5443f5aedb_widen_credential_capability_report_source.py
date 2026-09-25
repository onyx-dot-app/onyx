"""widen credential_capability_report.source

Revision ID: 4b5443f5aedb
Revises: ac05f4a21dbd
Create Date: 2026-09-24 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b5443f5aedb"
down_revision = "ac05f4a21dbd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The column was created as a non-native Enum(DocumentSource), which renders
    # as VARCHAR sized to the longest enum name at the time (20 characters).
    # Widen it to match the other source columns so longer names such as
    # JIRA_SERVICE_MANAGEMENT fit.
    op.alter_column(
        "credential_capability_report",
        "source",
        type_=sa.String(length=50),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing back to 20 characters would fail for rows whose source name is
    # longer, so the column is left at its widened size.
    pass
