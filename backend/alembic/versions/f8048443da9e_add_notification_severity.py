"""add notification severity

Revision ID: f8048443da9e
Revises: 8d1297b43210
Create Date: 2026-08-13 15:22:27.752583

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f8048443da9e"
down_revision = "8d1297b43210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default="INFO",
        ),
    )

    # Backfill the types that render as banners today so their banners
    # survive the switch to severity-driven eligibility.
    op.execute(
        """
        UPDATE notification
        SET severity = 'WARNING'
        WHERE notif_type IN ('TRIAL_ENDS_TWO_DAYS', 'SYSTEM_ANNOUNCEMENT')
        """
    )
    # License expiry: t_1d / grace stages and failed renewals render as
    # errors; earlier stages render as warnings. Mirrors _severity_for_stage
    # in ee/onyx/utils/license_notifications.py — duplicated here because
    # migrations must not import application code.
    op.execute(
        """
        UPDATE notification
        SET severity = CASE
            WHEN additional_data->>'stage' IN ('t_1d', 'grace')
                OR (additional_data->>'renewal_failed')::boolean IS TRUE
            THEN 'ERROR'
            ELSE 'WARNING'
        END
        WHERE notif_type = 'LICENSE_EXPIRY_WARNING'
        """
    )


def downgrade() -> None:
    op.drop_column("notification", "severity")
