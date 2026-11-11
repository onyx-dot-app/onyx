"""seed_default_image_gen_config

Revision ID: 9087b548dd69
Revises: 2b90f3af54b8
Create Date: 2026-01-05 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = "9087b548dd69"
down_revision = "2b90f3af54b8"
branch_labels = None
depends_on = None


# No-op: this used to seed a default image generation config. Config seeding
# belongs in tenant provisioning, not in a schema migration.
def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
