"""Add type to credentials

Revision ID: 4ea2c93919c1
Revises: 473a1a7ca408
Create Date: 2024-07-18 13:07:13.655895

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4ea2c93919c1"
down_revision = "473a1a7ca408"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Add the new 'source' column to the 'credential' table
    op.add_column(
        "credential",
        sa.Column(
            "source",
            sa.String(length=100),  # Use String instead of Enum
            nullable=True,  # Initially allow NULL values
        ),
    )
    op.add_column(
        "credential",
        sa.Column(
            "name",
            sa.String(),
            nullable=True,
        ),
    )

    # Create a temporary table that maps each credential to a single connector source.
    # This is needed because a credential can be associated with multiple connectors,
    # but we want to assign a single source to each credential.
    # We use DISTINCT ON to ensure we only get one row per credential_id.
    op.execute(
        """
    CREATE TEMPORARY TABLE temp_connector_credential AS
    SELECT DISTINCT ON (cc.credential_id)
        cc.credential_id,
        c.source AS connector_source
    FROM connector_credential_pair cc
    JOIN connector c ON cc.connector_id = c.id
    """
    )

    # Update the 'source' column in the 'credential' table
    op.execute(
        """
    UPDATE credential cred
    SET source = COALESCE(
        (SELECT connector_source
         FROM temp_connector_credential temp
         WHERE cred.id = temp.credential_id),
        'NOT_APPLICABLE'
    )
    """
    )
    # If no exception was raised, alter the column
    op.alter_column("credential", "source", nullable=True)  # TODO modify
    # # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_column("credential", "source")
    op.drop_column("credential", "name")
