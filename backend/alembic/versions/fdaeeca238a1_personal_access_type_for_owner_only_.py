"""personal access type for owner-only connectors

Adds the PERSONAL access type. Existing pairs keep their access type.
Data-access rows on types that take no groups are removed. creator_id becomes
a foreign key to the user.

Revision ID: fdaeeca238a1
Revises: c0de5e7a91b2
Create Date: 2026-11-08 17:29:24.007968

"""

from alembic import op
import sqlalchemy as sa

# access_type stores the AccessType member names, not their values.


# revision identifiers, used by Alembic.
revision = "fdaeeca238a1"
down_revision = "c0de5e7a91b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM user_group__cc_pair_data_access AS data_access
        USING connector_credential_pair AS cc_pair
        WHERE data_access.cc_pair_id = cc_pair.id
          AND cc_pair.access_type IN ('PUBLIC', 'SYNC', 'PERSONAL')
        """
    )

    # Pin the data-access rows to group access types: each row copies its
    # pair's access type, a CHECK limits it to group types, and the foreign key
    # matches (cc_pair_id, access_type) to the pair. ON UPDATE CASCADE lets a
    # pair move between PRIVATE and SYNC_RESTRICTED; moving to a type without
    # groups fails while rows remain.
    op.create_unique_constraint(
        "uq_connector_credential_pair_id_access_type",
        "connector_credential_pair",
        ["id", "access_type"],
    )
    op.add_column(
        "user_group__cc_pair_data_access",
        sa.Column("access_type", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE user_group__cc_pair_data_access AS data_access
        SET access_type = cc_pair.access_type
        FROM connector_credential_pair AS cc_pair
        WHERE cc_pair.id = data_access.cc_pair_id
        """
    )
    op.alter_column("user_group__cc_pair_data_access", "access_type", nullable=False)
    op.create_check_constraint(
        "ck_cc_pair_data_access_group_access_type",
        "user_group__cc_pair_data_access",
        "access_type IN ('PRIVATE', 'SYNC_RESTRICTED')",
    )
    op.drop_constraint(
        "user_group__cc_pair_data_access_cc_pair_id_fkey",
        "user_group__cc_pair_data_access",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_cc_pair_data_access_cc_pair_access_type",
        "user_group__cc_pair_data_access",
        "connector_credential_pair",
        ["cc_pair_id", "access_type"],
        ["id", "access_type"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )

    # creator_id reads a PERSONAL pair on an ownerless credential, so it must
    # name a real user. Clear ids of deleted users before adding the key.
    op.execute(
        """
        UPDATE connector_credential_pair
        SET creator_id = NULL
        WHERE creator_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM "user" WHERE "user".id = connector_credential_pair.creator_id
          )
        """
    )
    op.create_foreign_key(
        "connector_credential_pair_creator_id_fkey",
        "connector_credential_pair",
        "user",
        ["creator_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "connector_credential_pair_creator_id_fkey",
        "connector_credential_pair",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_cc_pair_data_access_cc_pair_access_type",
        "user_group__cc_pair_data_access",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_group__cc_pair_data_access_cc_pair_id_fkey",
        "user_group__cc_pair_data_access",
        "connector_credential_pair",
        ["cc_pair_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "ck_cc_pair_data_access_group_access_type",
        "user_group__cc_pair_data_access",
        type_="check",
    )
    op.drop_column("user_group__cc_pair_data_access", "access_type")
    op.drop_constraint(
        "uq_connector_credential_pair_id_access_type",
        "connector_credential_pair",
        type_="unique",
    )
    # A PERSONAL pair has no groups, so it maps back to PRIVATE with none.
    op.execute(
        """
        UPDATE connector_credential_pair
        SET access_type = 'PRIVATE'
        WHERE access_type = 'PERSONAL'
        """
    )
