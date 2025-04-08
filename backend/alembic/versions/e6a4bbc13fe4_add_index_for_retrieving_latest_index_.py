"""Add index for retrieving latest index_attempt

Revision ID: e6a4bbc13fe4
Revises: b082fec533f0
Create Date: 2023-08-10 12:37:23.335471

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "e6a4bbc13fe4"
down_revision = "b082fec533f0"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_index_attempt_latest_for_connector_credential_pair"),
        "index_attempt",
        ["connector_id", "credential_id", "time_created"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_index_attempt_latest_for_connector_credential_pair"),
        table_name="index_attempt",
    )
