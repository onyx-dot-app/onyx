"""remove rt

Revision ID: 949b4a92a401
Revises: 1b10e1fda030
Create Date: 2024-10-26 13:06:06.937969

"""

from alembic import op
from sqlalchemy.orm import Session
from sqlalchemy import text

# Import your models and constants
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
)


# revision identifiers, used by Alembic.
revision = "949b4a92a401"
down_revision = "1b10e1fda030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deletes all RequestTracker connectors and associated data
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get connectors using raw SQL
    result = bind.execute(
        text("SELECT id FROM connector WHERE source = 'requesttracker'")
    )
    connector_ids = [row[0] for row in result]

    if connector_ids:
        cc_pairs_to_delete = (
            session.query(ConnectorCredentialPair)
            .filter(ConnectorCredentialPair.connector_id.in_(connector_ids))
            .all()
        )

        cc_pair_ids = [cc_pair.id for cc_pair in cc_pairs_to_delete]

        if cc_pair_ids:
            session.query(IndexAttempt).filter(
                IndexAttempt.connector_credential_pair_id.in_(cc_pair_ids)
            ).delete(synchronize_session=False)

            session.query(ConnectorCredentialPair).filter(
                ConnectorCredentialPair.id.in_(cc_pair_ids)
            ).delete(synchronize_session=False)

        credential_ids = [cc_pair.credential_id for cc_pair in cc_pairs_to_delete]
        if credential_ids:
            session.query(Credential).filter(Credential.id.in_(credential_ids)).delete(
                synchronize_session=False
            )

        session.query(Connector).filter(Connector.id.in_(connector_ids)).delete(
            synchronize_session=False
        )

    session.commit()


def downgrade() -> None:
    # No-op downgrade as we cannot restore deleted data
    pass
