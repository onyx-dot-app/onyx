"""duplicated no-harm user file migration

Revision ID: 6a804aeb4830
Revises: 8e1ac4f39a9f
Create Date: 2025-04-01 07:26:10.539362

"""

# revision identifiers, used by Alembic.
revision = "6a804aeb4830"
down_revision = "8e1ac4f39a9f"
branch_labels = None
depends_on = None


# Leaving this around only because some people might be on this migration
# originally was a duplicate of the user files migration
def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
