"""Polling Document Count

Revision ID: 3c5e35aa9af0
Revises: 27c6ecc08586
Create Date: 2023-06-14 23:45:51.760440

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "3c5e35aa9af0"
down_revision = "27c6ecc08586"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "last_successful_index_time",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "last_attempt_status",
            sa.Enum(
                "NOT_STARTED",
                "IN_PROGRESS",
                "SUCCESS",
                "FAILED",
                name="indexingstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
    )
    op.add_column(
        "connector_credential_pair",
        sa.Column("total_docs_indexed", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("connector_credential_pair", "total_docs_indexed")
    op.drop_column("connector_credential_pair", "last_attempt_status")
    op.drop_column("connector_credential_pair", "last_successful_index_time")
