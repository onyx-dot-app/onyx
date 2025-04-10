"""Make 'last_attempt_status' nullable

Revision ID: b082fec533f0
Revises: df0c7ad8a076
Create Date: 2023-08-06 12:05:47.087325

"""

from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b082fec533f0"
down_revision = "df0c7ad8a076"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.alter_column(
        "connector_credential_pair",
        "last_attempt_status",
        existing_type=postgresql.ENUM(
            "NOT_STARTED",
            "IN_PROGRESS",
            "SUCCESS",
            "FAILED",
            name="indexingstatus",
        ),
        nullable=True,
    )


def downgrade() -> None:
    # First, update any null values to a default value
    op.execute(
        "UPDATE connector_credential_pair SET last_attempt_status = 'NOT_STARTED' WHERE last_attempt_status IS NULL"
    )

    # Then, make the column non-nullable
    op.alter_column(
        "connector_credential_pair",
        "last_attempt_status",
        existing_type=postgresql.ENUM(
            "NOT_STARTED",
            "IN_PROGRESS",
            "SUCCESS",
            "FAILED",
            name="indexingstatus",
        ),
        nullable=False,
    )
