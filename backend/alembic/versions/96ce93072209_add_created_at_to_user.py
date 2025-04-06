"""add_created_at_to_user

Revision ID: 96ce93072209
Revises: 3781a5eb12cb
Create Date: 2025-04-06 10:14:34.400809

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '96ce93072209'
down_revision = '3781a5eb12cb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add created_at column to user table if it doesn't exist
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'user' AND column_name = 'created_at'
        ) THEN
            ALTER TABLE "user" ADD COLUMN created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP;
        END IF;
    END $$;
    """)

def downgrade() -> None:
    # Remove created_at column from user table
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'user' AND column_name = 'created_at'
        ) THEN
            ALTER TABLE "user" DROP COLUMN created_at;
        END IF;
    END $$;
    """)


