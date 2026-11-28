"""integration oauth legacy redirect path

Revision ID: b37ec5bd7efa
Revises: 00a73eb4dccf
Create Date: 2026-11-28 00:18:39.824283

A new OAuth client of an API integration uses /integrations/oauth/callback.
An existing client keeps the redirect path that admins registered for it with
the provider: /craft/v1/apps/oauth/callback for a preset and
/oauth-config/callback for a manual client.
"""

from alembic import op
import sqlalchemy as sa


revision = "b37ec5bd7efa"
down_revision = "00a73eb4dccf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_oauth_client",
        sa.Column("legacy_redirect_path", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE integration_oauth_client AS client
        SET legacy_redirect_path = CASE client.provider_mode
            WHEN 'preset' THEN '/craft/v1/apps/oauth/callback'
            ELSE '/oauth-config/callback'
        END
        FROM integration
        WHERE integration.id = client.integration_id
          AND integration.kind = 'api'
          AND client.provider_mode IN ('preset', 'manual')
        """
    )


def downgrade() -> None:
    op.drop_column("integration_oauth_client", "legacy_redirect_path")
