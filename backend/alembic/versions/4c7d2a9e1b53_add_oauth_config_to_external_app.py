"""add oauth_config to external_app

Revision ID: 4c7d2a9e1b53
Revises: b7c2e4f1a9d3
Create Date: 2026-10-01 12:00:00.000000

Admin-defined OAuth 2.0 flow parameters for CUSTOM external apps. NULL means
the app uses static credentials; always NULL for built-in app types (their
flow comes from the provider), enforced by a check constraint.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "4c7d2a9e1b53"
down_revision = "b7c2e4f1a9d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_app",
        sa.Column("oauth_config", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_external_app_oauth_config_custom_only",
        "external_app",
        "app_type = 'CUSTOM' OR oauth_config IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_external_app_oauth_config_custom_only", "external_app", type_="check"
    )
    op.drop_column("external_app", "oauth_config")
