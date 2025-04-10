"""Remove Native Enum

Revision ID: 46625e4745d4
Revises: 9d97fecfab7f
Create Date: 2023-10-27 11:38:33.803145

"""

from alembic import op
from sqlalchemy import String

# revision identifiers, used by Alembic.
revision = "46625e4745d4"
down_revision = "9d97fecfab7f"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # At this point, we directly changed some previous migrations,
    # https://github.com/onyx-dot-app/onyx/pull/637
    # Due to using Postgres native Enums, it caused some complications for first time users.
    # To remove those complications, all Enums are only handled application side moving forward.
    # This migration exists to ensure that existing users don't run into upgrade issues.
    op.alter_column("index_attempt", "status", type_=String)
    op.alter_column("connector_credential_pair", "last_attempt_status", type_=String)
    op.execute("DROP TYPE IF EXISTS indexingstatus")


def downgrade() -> None:
    # We don't want Native Enums, do nothing
    pass
