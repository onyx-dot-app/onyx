"""Add has_been_indexed to DocumentByConnectorCredentialPair

Revision ID: c7bf5721733e
Revises: fec3db967bf7
Create Date: 2025-01-13 12:39:05.831693

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c7bf5721733e"
down_revision = "027381bce97c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # assume all existing rows have been indexed, no better approach
    op.add_column(
        "document_by_connector_credential_pair",
        sa.Column("has_been_indexed", sa.Boolean(), nullable=True),
    )
    op.execute(
        "UPDATE document_by_connector_credential_pair SET has_been_indexed = TRUE"
    )
    op.alter_column(
        "document_by_connector_credential_pair",
        "has_been_indexed",
        nullable=False,
    )

    # Add index to optimize get_document_counts_for_cc_pairs query pattern
    op.create_index(
        "idx_document_cc_pair_counts",
        "document_by_connector_credential_pair",
        ["connector_id", "credential_id", "has_been_indexed"],
        unique=False,
    )


def downgrade() -> None:
    # Remove the index first before removing the column
    op.drop_index(
        "idx_document_cc_pair_counts",
        table_name="document_by_connector_credential_pair",
    )
    op.drop_column("document_by_connector_credential_pair", "has_been_indexed")
