"""Add a domain-only fleet signup inventory view.

Revision ID: b67c3fa177d6
Revises: 1b26b1dfdc54
"""

from alembic import op

revision = "b67c3fa177d6"
down_revision = "1b26b1dfdc54"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE VIEW fleet_signup_email_domains WITH (security_barrier=true) AS
        SELECT lower(split_part(email,'@',2)) AS domain,
               min(created_at) AS first_signup_at
        FROM "user"
        WHERE account_type='STANDARD' AND email ~ '^[^@]+@[^@]+$'
        GROUP BY lower(split_part(email,'@',2))""")


def downgrade() -> None:
    op.execute("DROP VIEW fleet_signup_email_domains")
