"""make lti google drive credentials private

Revision ID: e459af7025d2
Revises: a752b75e4f63
Create Date: 2026-08-06 16:02:12.057316

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e459af7025d2"
down_revision = "a752b75e4f63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The prior shared-token flow allowed multiple instructors to overwrite the
    # same credential. Its user_id therefore cannot establish who owns the
    # stored refresh token. Make each legacy credential private and invalidate
    # its OAuth payload so its owner must complete consent again.
    op.execute(
        sa.text(
            """
            UPDATE credential
            SET admin_public = false,
                curator_public = false,
                credential_json = NULL
            WHERE source = 'GOOGLE_DRIVE'
              AND is_lti_credential = true
            """
        )
    )
    # Token ownership cannot be proven for any pair created by the shared flow,
    # including a pair whose creator happens to match credential.user_id. Retire
    # all legacy pairs; the standard connector deletion worker removes their
    # indexed copies without modifying any files in Google Drive.
    op.execute(
        sa.text(
            """
            UPDATE connector_credential_pair AS cc_pair
            SET status = 'DELETING'
            FROM credential
            WHERE credential.id = cc_pair.credential_id
              AND credential.source = 'GOOGLE_DRIVE'
              AND credential.is_lti_credential = true
              AND cc_pair.status != 'DELETING'
            """
        )
    )


def downgrade() -> None:
    # Do not restore invalidated refresh tokens or reactivate legacy pairs.
    pass
