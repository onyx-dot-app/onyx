"""reindex outlook connectors for thread documents

Outlook now writes one document per thread with ids the per-mailbox walk never
produced. A poll run only rebuilds threads with new mail, and the next prune
drops every per-mailbox document, so each Outlook connector is marked for a
full re-index to carry the rest over.

Revision ID: 1b26b1dfdc54
Revises: 84c15650b1ad

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1b26b1dfdc54"
down_revision = "84c15650b1ad"
branch_labels = None
depends_on = None

# Enum names as the non-native columns store them.
OUTLOOK_SOURCE = "OUTLOOK"
REINDEX_TRIGGER = "REINDEX"

connector_table = sa.table(
    "connector",
    sa.column("id", sa.Integer),
    sa.column("source", sa.String),
)
cc_pair_table = sa.table(
    "connector_credential_pair",
    sa.column("connector_id", sa.Integer),
    sa.column("indexing_trigger", sa.String),
)


def _outlook_connector_ids() -> sa.Select:
    return sa.select(connector_table.c.id).where(
        connector_table.c.source == OUTLOOK_SOURCE
    )


def upgrade() -> None:
    op.execute(
        sa.update(cc_pair_table)
        .where(
            cc_pair_table.c.connector_id.in_(_outlook_connector_ids()),
            cc_pair_table.c.indexing_trigger.is_(None),
        )
        .values(indexing_trigger=REINDEX_TRIGGER)
    )


def downgrade() -> None:
    # The trigger is consumed by the next indexing run, so clearing the ones
    # this revision set is the only state to put back.
    op.execute(
        sa.update(cc_pair_table)
        .where(
            cc_pair_table.c.connector_id.in_(_outlook_connector_ids()),
            cc_pair_table.c.indexing_trigger == REINDEX_TRIGGER,
        )
        .values(indexing_trigger=None)
    )
