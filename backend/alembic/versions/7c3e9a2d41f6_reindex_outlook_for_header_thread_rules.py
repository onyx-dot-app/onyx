"""reindex outlook connectors for header thread rules

Outlook now decides each thread's builder and readers from message headers,
and a mailbox the first message does not name writes its own document under
an id the earlier walk never produced. A poll only rebuilds threads with new
mail, so each Outlook connector is marked for a full re-index to carry the
rest over.

Revision ID: 7c3e9a2d41f6
Revises: 1b26b1dfdc54

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7c3e9a2d41f6"
down_revision = "1b26b1dfdc54"
branch_labels = None
depends_on = None

# Enum names as the non-native columns store them.
OUTLOOK_SOURCE = "OUTLOOK"
UPDATE_TRIGGER = "UPDATE"
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
            # A pending incremental run would consume the trigger without
            # rebuilding the threads that gained no mail.
            sa.or_(
                cc_pair_table.c.indexing_trigger.is_(None),
                cc_pair_table.c.indexing_trigger == UPDATE_TRIGGER,
            ),
        )
        .values(indexing_trigger=REINDEX_TRIGGER)
    )


def downgrade() -> None:
    # The trigger is consumed by the next indexing run, so clearing the ones
    # this revision set is the only state to put back. A pending UPDATE it
    # raised comes back as no trigger.
    op.execute(
        sa.update(cc_pair_table)
        .where(
            cc_pair_table.c.connector_id.in_(_outlook_connector_ids()),
            cc_pair_table.c.indexing_trigger == REINDEX_TRIGGER,
        )
        .values(indexing_trigger=None)
    )
