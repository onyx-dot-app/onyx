"""index the connector event inbox claim by pair

Every claim reads one pair's pending rows in id order.

Revision ID: 70aed6c27639
Revises: d451809a0c3e
Create Date: 2026-11-03 13:24:59.089337

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "70aed6c27639"
down_revision = "d451809a0c3e"
branch_labels = None
depends_on = None


def _recreate_claim_index(columns: list[str]) -> None:
    op.drop_index(
        "ix_connector_event_inbox_claim",
        table_name="connector_event_inbox",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_connector_event_inbox_claim",
        "connector_event_inbox",
        columns,
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def upgrade() -> None:
    _recreate_claim_index(["connector_credential_pair_id", "id"])


def downgrade() -> None:
    _recreate_claim_index(["available_at", "id"])
