"""updated constraints for ccpairs

Revision ID: f7505c5b0284
Revises: f71470ba9274
Create Date: 2025-04-01 17:50:42.504818

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "f7505c5b0284"
down_revision = "f71470ba9274"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Drop the old foreign-key constraints
    op.drop_constraint(
        "document_by_connector_credential_pair_connector_id_fkey",
        "document_by_connector_credential_pair",
        type_="foreignkey",
    )
    op.drop_constraint(
        "document_by_connector_credential_pair_credential_id_fkey",
        "document_by_connector_credential_pair",
        type_="foreignkey",
    )

    # 2) Re-add them with ondelete='CASCADE'
    op.create_foreign_key(
        "document_by_connector_credential_pair_connector_id_fkey",
        source_table="document_by_connector_credential_pair",
        referent_table="connector",
        local_cols=["connector_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "document_by_connector_credential_pair_credential_id_fkey",
        source_table="document_by_connector_credential_pair",
        referent_table="credential",
        local_cols=["credential_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Reverse the changes for rollback
    op.drop_constraint(
        "document_by_connector_credential_pair_connector_id_fkey",
        "document_by_connector_credential_pair",
        type_="foreignkey",
    )
    op.drop_constraint(
        "document_by_connector_credential_pair_credential_id_fkey",
        "document_by_connector_credential_pair",
        type_="foreignkey",
    )

    # Recreate without CASCADE
    op.create_foreign_key(
        "document_by_connector_credential_pair_connector_id_fkey",
        "document_by_connector_credential_pair",
        "connector",
        ["connector_id"],
        ["id"],
    )
    op.create_foreign_key(
        "document_by_connector_credential_pair_credential_id_fkey",
        "document_by_connector_credential_pair",
        "credential",
        ["credential_id"],
        ["id"],
    )
