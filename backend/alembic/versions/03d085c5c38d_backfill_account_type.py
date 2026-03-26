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
API_KEY_EMAIL_PATTERN = "API_KEY__%@%.onyxapikey.ai"


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # Step 1: Backfill account_type from role.
    # Order matters — most-specific matches first so the final catch-all
    # only touches rows that haven't been classified yet.
    # ------------------------------------------------------------------

    # 1a. API key virtual users (any role) → SERVICE_ACCOUNT
    conn.execute(
        sa.text(
            'UPDATE "user" SET account_type = :acct_type '
            "WHERE email LIKE :pattern AND account_type IS NULL"
        ),
        {"acct_type": _SERVICE_ACCOUNT, "pattern": API_KEY_EMAIL_PATTERN},
    )

    # 1b. Anonymous user → ANONYMOUS
    conn.execute(
        sa.text(
            'UPDATE "user" SET account_type = :acct_type '
            "WHERE id = :anon_id AND account_type IS NULL"
        ),
        {"acct_type": _ANONYMOUS, "anon_id": ANONYMOUS_USER_ID},
    )

    # 1c. SLACK_USER → BOT
    conn.execute(
        sa.text(
            'UPDATE "user" SET account_type = :acct_type '
            "WHERE role = 'slack_user' AND account_type IS NULL"
        ),
        {"acct_type": _BOT},
    )

    # 1d. EXT_PERM_USER → EXT_PERM_USER
    conn.execute(
        sa.text(
            'UPDATE "user" SET account_type = :acct_type '
            "WHERE role = 'ext_perm_user' AND account_type IS NULL"
        ),
        {"acct_type": _EXT_PERM_USER},
    )

    # 1e. Remaining (ADMIN, BASIC, CURATOR, GLOBAL_CURATOR) → STANDARD
    conn.execute(
        sa.text(
            'UPDATE "user" SET account_type = :acct_type ' "WHERE account_type IS NULL"
        ),
        {"acct_type": _STANDARD},
    )

    # ------------------------------------------------------------------
    # Step 2: Set account_type to NOT NULL now that every row is filled.
    # ------------------------------------------------------------------
    op.alter_column("user", "account_type", nullable=False)


def downgrade() -> None:
    conn = op.get_bind()

    # Clear backfilled values
    conn.execute(sa.text('UPDATE "user" SET account_type = NULL'))

    # Revert to nullable
    op.alter_column("user", "account_type", nullable=True)
