"""Add ID to ConnectorCredentialPair

Revision ID: 800f48024ae9
Revises: 767f1c2a00eb
Create Date: 2023-09-19 16:13:42.299715

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.schema import Sequence, CreateSequence

# revision identifiers, used by Alembic.
revision = "800f48024ae9"
down_revision = "767f1c2a00eb"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    sequence = Sequence("connector_credential_pair_id_seq")
    op.execute(CreateSequence(sequence))  # type: ignore
    op.add_column(
        "connector_credential_pair",
        sa.Column(
            "id", sa.Integer(), nullable=True, server_default=sequence.next_value()
        ),
    )
    op.add_column(
        "connector_credential_pair",
        sa.Column("name", sa.String(), nullable=True),
    )

    # fill in IDs for existing rows
    op.execute(
        "UPDATE connector_credential_pair SET id = nextval('connector_credential_pair_id_seq') WHERE id IS NULL"
    )
    op.alter_column("connector_credential_pair", "id", nullable=False)

    op.create_unique_constraint(
        "connector_credential_pair__name__key", "connector_credential_pair", ["name"]
    )
    op.create_unique_constraint(
        "connector_credential_pair__id__key", "connector_credential_pair", ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "connector_credential_pair__name__key",
        "connector_credential_pair",
        type_="unique",
    )
    op.drop_constraint(
        "connector_credential_pair__id__key",
        "connector_credential_pair",
        type_="unique",
    )
    op.drop_column("connector_credential_pair", "name")
    op.drop_column("connector_credential_pair", "id")
    op.execute("DROP SEQUENCE connector_credential_pair_id_seq")
