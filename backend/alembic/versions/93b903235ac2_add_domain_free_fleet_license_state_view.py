"""Add a boolean-only fleet license state view.

Revision ID: 93b903235ac2
Revises: b67c3fa177d6
"""

from alembic import op

revision = "93b903235ac2"
down_revision = "b67c3fa177d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE VIEW fleet_license_state WITH (security_barrier=true) AS
        SELECT coalesce(bool_or(length(license_data)>0),false) AS license_present,
               min(created_at) FILTER (WHERE length(license_data)>0) AS first_set_at
        FROM license""")


def downgrade() -> None:
    op.execute("DROP VIEW fleet_license_state")
