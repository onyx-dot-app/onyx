"""backfill_account_type

Revision ID: 03d085c5c38d
Revises: 977e834c1427
Create Date: 2026-03-25 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "03d085c5c38d"
down_revision = "977e834c1427"
branch_labels = None
depends_on = None

_STANDARD = "STANDARD"
_BOT = "BOT"
_EXT_PERM_USER = "EXT_PERM_USER"
_SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
_ANONYMOUS = "ANONYMOUS"

# Well-known anonymous user UUID
ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000002"

# Email pattern for API key virtual users
API_KEY_EMAIL_PATTERN = r"API\_KEY\_\_%"

# Reflect the table structure for use in DML
user_table = sa.table(
    "user",
    sa.column("id", sa.Uuid),
    sa.column("email", sa.String),
    sa.column("role", sa.String),
    sa.column("account_type", sa.String),
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1: Backfill account_type from role.
    # Order matters — most-specific matches first so the final catch-all
    # only touches rows that haven't been classified yet.
    # ------------------------------------------------------------------

    # 1a. API key virtual users → SERVICE_ACCOUNT
    op.execute(
        sa.update(user_table)
        .where(
            user_table.c.email.ilike(API_KEY_EMAIL_PATTERN),
            user_table.c.account_type.is_(None),
        )
        .values(account_type=_SERVICE_ACCOUNT)
    )

    # 1b. Anonymous user → ANONYMOUS
    op.execute(
        sa.update(user_table)
        .where(
            user_table.c.id == ANONYMOUS_USER_ID,
            user_table.c.account_type.is_(None),
        )
        .values(account_type=_ANONYMOUS)
    )

    # 1c. SLACK_USER role → BOT
    op.execute(
        sa.update(user_table)
        .where(
            user_table.c.role == "SLACK_USER",
            user_table.c.account_type.is_(None),
        )
        .values(account_type=_BOT)
    )

    # 1d. EXT_PERM_USER role → EXT_PERM_USER
    op.execute(
        sa.update(user_table)
        .where(
            user_table.c.role == "EXT_PERM_USER",
            user_table.c.account_type.is_(None),
        )
        .values(account_type=_EXT_PERM_USER)
    )

    # 1e. Everything else → STANDARD
    op.execute(
        sa.update(user_table)
        .where(user_table.c.account_type.is_(None))
        .values(account_type=_STANDARD)
    )

    # ------------------------------------------------------------------
    # Step 2: Set account_type to NOT NULL now that every row is filled.
    # ------------------------------------------------------------------
    op.alter_column(
        "user",
        "account_type",
        nullable=False,
        server_default="STANDARD",
    )


def downgrade() -> None:
    op.alter_column("user", "account_type", nullable=True, server_default=None)
    op.execute(sa.update(user_table).values(account_type=None))
