"""associate index attempts with ccpair

Revision ID: 8a87bd6ec550
Revises: 4ea2c93919c1
Create Date: 2024-07-22 15:15:52.558451

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8a87bd6ec550"
down_revision = "4ea2c93919c1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Add the new connector_credential_pair_id column
    op.add_column(
        "index_attempt",
        sa.Column("connector_credential_pair_id", sa.Integer(), nullable=True),
    )

    # Create a foreign key constraint to the connector_credential_pair table
    op.create_foreign_key(
        "fk_index_attempt_connector_credential_pair_id",
        "index_attempt",
        "connector_credential_pair",
        ["connector_credential_pair_id"],
        ["id"],
    )

    # Populate the new connector_credential_pair_id column using existing connector_id and credential_id
    op.execute(
        """
        UPDATE index_attempt ia
        SET connector_credential_pair_id = (
            SELECT id FROM connector_credential_pair ccp
            WHERE
                (ia.connector_id IS NULL OR ccp.connector_id = ia.connector_id)
                AND (ia.credential_id IS NULL OR ccp.credential_id = ia.credential_id)
            LIMIT 1
        )
        WHERE ia.connector_id IS NOT NULL OR ia.credential_id IS NOT NULL
        """
    )

    # For good measure
    op.execute(
        """
        DELETE FROM index_attempt
        WHERE connector_credential_pair_id IS NULL
        """
    )

    # Make the new connector_credential_pair_id column non-nullable
    op.alter_column("index_attempt", "connector_credential_pair_id", nullable=False)

    # Drop the old connector_id and credential_id columns
    op.drop_column("index_attempt", "connector_id")
    op.drop_column("index_attempt", "credential_id")

    # Update the index to use connector_credential_pair_id
    op.create_index(
        "ix_index_attempt_latest_for_connector_credential_pair",
        "index_attempt",
        ["connector_credential_pair_id", "time_created"],
    )


def downgrade() -> None:
    # Add back the old connector_id and credential_id columns
    op.add_column(
        "index_attempt", sa.Column("connector_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "index_attempt", sa.Column("credential_id", sa.Integer(), nullable=True)
    )

    # Populate the old connector_id and credential_id columns using the connector_credential_pair_id
    op.execute(
        """
        UPDATE index_attempt ia
        SET connector_id = ccp.connector_id, credential_id = ccp.credential_id
        FROM connector_credential_pair ccp
        WHERE ia.connector_credential_pair_id = ccp.id
        """
    )

    # Make the old connector_id and credential_id columns non-nullable
    op.alter_column("index_attempt", "connector_id", nullable=False)
    op.alter_column("index_attempt", "credential_id", nullable=False)

    # Drop the new connector_credential_pair_id column
    op.drop_constraint(
        "fk_index_attempt_connector_credential_pair_id",
        "index_attempt",
        type_="foreignkey",
    )
    op.drop_column("index_attempt", "connector_credential_pair_id")

    op.create_index(
        "ix_index_attempt_latest_for_connector_credential_pair",
        "index_attempt",
        ["connector_id", "credential_id", "time_created"],
    )
