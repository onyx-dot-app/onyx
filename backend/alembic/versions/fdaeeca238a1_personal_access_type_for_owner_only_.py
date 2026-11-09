"""personal access type for owner-only connectors

A PRIVATE pair with no data-access group is read by its credential owner only.
That state now has its own access type, PERSONAL, so PRIVATE always means a
groups choice. Pairs on an ownerless credential stay PRIVATE. Data-access rows
on types that take no groups are removed.

Revision ID: fdaeeca238a1
Revises: c0de5e7a91b2
Create Date: 2026-11-08 17:29:24.007968

"""

from alembic import op

# access_type stores the AccessType member names, not their values.


# revision identifiers, used by Alembic.
revision = "fdaeeca238a1"
down_revision = "c0de5e7a91b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE connector_credential_pair
        SET access_type = 'PERSONAL'
        WHERE access_type = 'PRIVATE'
          AND NOT EXISTS (
            SELECT 1
            FROM user_group__cc_pair_data_access AS data_access
            WHERE data_access.cc_pair_id = connector_credential_pair.id
          )
          -- Ownerless credentials stay PRIVATE: nobody reads those pairs today,
          -- and PERSONAL would give their creator access.
          AND EXISTS (
            SELECT 1
            FROM credential
            WHERE credential.id = connector_credential_pair.credential_id
              AND credential.user_id IS NOT NULL
          )
        """
    )
    op.execute(
        """
        DELETE FROM user_group__cc_pair_data_access AS data_access
        USING connector_credential_pair AS cc_pair
        WHERE data_access.cc_pair_id = cc_pair.id
          AND cc_pair.access_type IN ('PUBLIC', 'SYNC', 'PERSONAL')
        """
    )


def downgrade() -> None:
    # A PERSONAL pair has no groups, so it maps back to PRIVATE with none.
    op.execute(
        """
        UPDATE connector_credential_pair
        SET access_type = 'PRIVATE'
        WHERE access_type = 'PERSONAL'
        """
    )
