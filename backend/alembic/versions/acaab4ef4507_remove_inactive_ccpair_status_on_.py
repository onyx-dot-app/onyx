"""remove inactive ccpair status on downgrade

Revision ID: acaab4ef4507
Revises: b388730a2899
Create Date: 2025-02-16 18:21:41.330212

"""

from alembic import op
from onyx.db.models import ConnectorCredentialPair
from onyx.db.enums import ConnectorCredentialPairStatus
from sqlalchemy import update

# revision identifiers, used by Alembic.
revision = "acaab4ef4507"
down_revision = "b388730a2899"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    op.execute(
        update(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.status == ConnectorCredentialPairStatus.INVALID)
        .values(status=ConnectorCredentialPairStatus.ACTIVE)
    )
