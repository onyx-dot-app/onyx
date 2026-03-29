"""assign_users_to_default_groups

Revision ID: b7bcc991d722
Revises: 03d085c5c38d
Create Date: 2026-03-25 16:30:39.529301

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7bcc991d722"
down_revision = "03d085c5c38d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Look up default group IDs
    admin_row = conn.execute(
        sa.text(
            "SELECT id FROM user_group " "WHERE name = 'Admin' AND is_default = true"
        )
    ).fetchone()

    basic_row = conn.execute(
        sa.text(
            "SELECT id FROM user_group " "WHERE name = 'Basic' AND is_default = true"
        )
    ).fetchone()

    if admin_row is None:
        raise RuntimeError(
            "Default 'Admin' group not found. "
            "Ensure migration 977e834c1427 (seed_default_groups) ran successfully."
        )

    if basic_row is None:
        raise RuntimeError(
            "Default 'Basic' group not found. "
            "Ensure migration 977e834c1427 (seed_default_groups) ran successfully."
        )

    # Users with role=admin → Admin group
    # Exclude inactive placeholder/anonymous users that are not real users
    conn.execute(
        sa.text(
            "INSERT INTO user__user_group (user_group_id, user_id) "
            'SELECT :gid, id FROM "user" '
            "WHERE role = 'ADMIN' AND is_active = true "
            "ON CONFLICT (user_group_id, user_id) DO NOTHING"
        ),
        {"gid": admin_row[0]},
    )

    # STANDARD users (non-admin) and SERVICE_ACCOUNT users (role=basic) → Basic group
    # Exclude inactive placeholder/anonymous users that are not real users
    conn.execute(
        sa.text(
            "INSERT INTO user__user_group (user_group_id, user_id) "
            'SELECT :gid, id FROM "user" '
            "WHERE is_active = true AND ("
            "(account_type = 'STANDARD' AND role != 'ADMIN') "
            "OR (account_type = 'SERVICE_ACCOUNT' AND role = 'BASIC')"
            ") "
            "ON CONFLICT (user_group_id, user_id) DO NOTHING"
        ),
        {"gid": basic_row[0]},
    )


def downgrade() -> None:
    # Group memberships are left in place — removing them risks
    # deleting memberships that existed before this migration.
    pass
