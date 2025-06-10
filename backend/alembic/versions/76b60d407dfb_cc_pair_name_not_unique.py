"""CC-Pair Name not Unique

Revision ID: 76b60d407dfb
Revises: b156fa702355
Create Date: 2023-12-22 21:42:10.018804

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "76b60d407dfb"
down_revision = "b156fa702355"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("DELETE FROM connector_credential_pair WHERE name IS NULL")
    op.drop_constraint(
        "connector_credential_pair__name__key",
        "connector_credential_pair",
        type_="unique",
    )
    op.alter_column(
        "connector_credential_pair", "name", existing_type=sa.String(), nullable=False
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "connector_credential_pair__name__key", "connector_credential_pair", ["name"]
    )
    op.alter_column(
        "connector_credential_pair", "name", existing_type=sa.String(), nullable=True
    )
