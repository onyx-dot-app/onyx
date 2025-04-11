"""Moved status to connector credential pair

Revision ID: 4a951134c801
Revises: 7477a5f5d728
Create Date: 2024-08-10 19:20:34.527559

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4a951134c801"
down_revision = "7477a5f5d728"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "PAUSED",
                "DELETING",
                name="connectorcredentialpairstatus",
                native_enum=False,
            ),
            nullable=True,
        ),
    )

    # Update status of connector_credential_pair based on connector's disabled status
    op.execute(
        """
        UPDATE connector_credential_pair
        SET status = CASE
            WHEN (
                SELECT disabled
                FROM connector
                WHERE connector.id = connector_credential_pair.connector_id
            ) = FALSE THEN 'ACTIVE'
            ELSE 'PAUSED'
        END
        """
    )

    # Make the status column not nullable after setting values
    op.alter_column("connector_credential_pair", "status", nullable=False)

    op.drop_column("connector", "disabled")


def downgrade() -> None:
    op.add_column(
        "connector",
        sa.Column("disabled", sa.BOOLEAN(), autoincrement=False, nullable=True),
    )

    # Update disabled status of connector based on connector_credential_pair's status
    op.execute(
        """
        UPDATE connector
        SET disabled = CASE
            WHEN EXISTS (
                SELECT 1
                FROM connector_credential_pair
                WHERE connector_credential_pair.connector_id = connector.id
                AND connector_credential_pair.status = 'ACTIVE'
            ) THEN FALSE
            ELSE TRUE
        END
        """
    )

    # Make the disabled column not nullable after setting values
    op.alter_column("connector", "disabled", nullable=False)

    op.drop_column("connector_credential_pair", "status")
