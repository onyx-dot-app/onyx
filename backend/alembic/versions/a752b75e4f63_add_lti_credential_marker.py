"""add lti credential marker

Revision ID: a752b75e4f63
Revises: ea6bcc383329
Create Date: 2026-07-14 00:37:22.399907

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a752b75e4f63"
down_revision = "ea6bcc383329"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "credential",
        sa.Column(
            "is_lti_credential",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # A connector's LTI context is server-managed and therefore provides a
    # trustworthy backfill signal for credentials created before this marker.
    op.execute(
        sa.text(
            """
            UPDATE credential AS credential
            SET is_lti_credential = true
            FROM connector_credential_pair AS cc_pair
            JOIN connector ON connector.id = cc_pair.connector_id
            WHERE credential.id = cc_pair.credential_id
              AND connector.source = 'GOOGLE_DRIVE'
              AND connector.connector_specific_config ? 'lti_context_id'
            """
        )
    )
    op.alter_column("credential", "is_lti_credential", server_default=None)


def downgrade() -> None:
    op.drop_column("credential", "is_lti_credential")
