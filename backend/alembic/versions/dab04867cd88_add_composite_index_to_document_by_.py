"""Add composite index to document_by_connector_credential_pair

Revision ID: dab04867cd88
Revises: 54a74a0417fc
Create Date: 2024-12-13 22:43:20.119990

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "dab04867cd88"
down_revision = "54a74a0417fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index on (connector_id, credential_id)
    op.create_index(
        "idx_document_cc_pair_connector_credential",
        "document_by_connector_credential_pair",
        ["connector_id", "credential_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_document_cc_pair_connector_credential",
        table_name="document_by_connector_credential_pair",
    )
