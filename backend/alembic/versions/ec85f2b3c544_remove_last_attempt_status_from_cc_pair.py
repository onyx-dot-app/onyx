"""Remove Last Attempt Status from CC Pair

Revision ID: ec85f2b3c544
Revises: 3879338f8ba1
Create Date: 2024-05-23 21:39:46.126010

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ec85f2b3c544"
down_revision = "70f00c45c0f2"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("connector_credential_pair", "last_attempt_status")


def downgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "last_attempt_status",
            sa.VARCHAR(),
            autoincrement=False,
            nullable=True,
        ),
    )
