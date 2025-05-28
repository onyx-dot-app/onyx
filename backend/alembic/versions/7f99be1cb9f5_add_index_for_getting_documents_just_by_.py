"""Add index for getting documents just by connector id / credential id

Revision ID: 7f99be1cb9f5
Revises: 78dbe7e38469
Create Date: 2023-10-15 22:48:15.487762

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "7f99be1cb9f5"
down_revision = "78dbe7e38469"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        op.f(
            "ix_document_by_connector_credential_pair_pkey__connector_id__credential_id"
        ),
        "document_by_connector_credential_pair",
        ["connector_id", "credential_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f(
            "ix_document_by_connector_credential_pair_pkey__connector_id__credential_id"
        ),
        table_name="document_by_connector_credential_pair",
    )
