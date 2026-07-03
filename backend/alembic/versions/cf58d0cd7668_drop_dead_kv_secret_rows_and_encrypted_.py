"""drop dead kv secret rows and encrypted_value column

Revision ID: cf58d0cd7668
Revises: f6b0949ea33d
Create Date: 2026-07-02 18:50:58.728665

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "cf58d0cd7668"
down_revision = "f6b0949ea33d"
branch_labels = None
depends_on = None


key_value_store = sa.table("key_value_store", sa.column("key", sa.String))

# Global secrets now stored in encrypted_key_value_store; their KV rows are dead.
DEAD_KEYS = [
    "google_drive_app_credential",
    "gmail_app_credential",
    "customer_uuid",
    "instance_domain",
]


def upgrade() -> None:
    op.execute(key_value_store.delete().where(key_value_store.c.key.in_(DEAD_KEYS)))
    op.drop_column("key_value_store", "encrypted_value")


def downgrade() -> None:
    op.add_column(
        "key_value_store",
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
    )
