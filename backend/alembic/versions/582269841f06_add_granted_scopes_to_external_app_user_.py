"""add granted_scopes to external_app_user_credential

Adds a queryable, unencrypted column for the OAuth scopes a user actually
granted for an external app. Authorization metadata (not a secret), so it lives
alongside — not inside — the encrypted ``user_credentials`` blob.

Nullable: NULL distinguishes "no authoritative grant recorded" (provider
doesn't report scopes, or the best-effort lookup failed) from a known granted
set. Existing rows backfill to NULL, which is the correct "unknown" state.

Revision ID: 582269841f06
Revises: 989bc57562e4
Create Date: 2026-07-01 12:09:19.735991

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "582269841f06"
down_revision = "989bc57562e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_app_user_credential",
        sa.Column(
            "granted_scopes",
            postgresql.ARRAY(sa.String()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("external_app_user_credential", "granted_scopes")
