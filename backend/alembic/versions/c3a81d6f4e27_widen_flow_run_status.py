"""Widen flow_run status for the awaiting-decision state

Revision ID: c3a81d6f4e27
Revises: b7f2c4a19d33
Create Date: 2026-06-03 16:22:41.089517

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3a81d6f4e27"
down_revision = "b7f2c4a19d33"
branch_labels = None
depends_on = None


# The column was sized to the longest status at the time ("SUCCEEDED").
# A human step parks a run on AWAITING_DECISION, which does not fit.
NEW_LENGTH = 17
OLD_LENGTH = 9


def upgrade() -> None:
    op.alter_column(
        "flow_run",
        "status",
        existing_type=sa.String(length=OLD_LENGTH),
        type_=sa.String(length=NEW_LENGTH),
        existing_nullable=False,
        existing_server_default="QUEUED",
    )


def downgrade() -> None:
    # Parked runs cannot be represented in the narrower column, so fail them
    # rather than truncating a status into something that reads as success.
    op.execute(
        "UPDATE flow_run SET status = 'FAILED', "
        "error_class = 'node_exception', "
        "error_detail = 'run was awaiting a decision when the schema was "
        "rolled back' WHERE status = 'AWAITING_DECISION'"
    )
    op.alter_column(
        "flow_run",
        "status",
        existing_type=sa.String(length=NEW_LENGTH),
        type_=sa.String(length=OLD_LENGTH),
        existing_nullable=False,
        existing_server_default="QUEUED",
    )
