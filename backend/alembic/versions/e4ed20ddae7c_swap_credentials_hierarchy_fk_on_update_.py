"""swap_credentials_hierarchy_fk_on_update_cascade

Revision ID: e4ed20ddae7c
Revises: b6d184cfdaf3
Create Date: 2026-05-13 11:24:28.753104

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e4ed20ddae7c"
down_revision = "28429dd43807"
branch_labels = None
depends_on = None


FK_NAME = "hierarchy_node_by_connector_cre_connector_id_credential_id_fkey"
TABLE_NAME = "hierarchy_node_by_connector_credential_pair"


def upgrade() -> None:
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.create_foreign_key(
        FK_NAME,
        TABLE_NAME,
        "connector_credential_pair",
        ["connector_id", "credential_id"],
        ["connector_id", "credential_id"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.create_foreign_key(
        FK_NAME,
        TABLE_NAME,
        "connector_credential_pair",
        ["connector_id", "credential_id"],
        ["connector_id", "credential_id"],
        ondelete="CASCADE",
    )
