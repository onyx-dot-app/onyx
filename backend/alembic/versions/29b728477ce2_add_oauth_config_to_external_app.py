"""add oauth_config to external_app

Revision ID: 29b728477ce2
Revises: 1cb59a95b250
Create Date: 2026-06-11 14:47:15.516308

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "29b728477ce2"
down_revision = "1cb59a95b250"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Admin-defined OAuth 2.0 flow parameters for CUSTOM apps; NULL means the
    # app uses static credentials (and always NULL for built-in app types).
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
