"""add token_usage to chat_message

Revision ID: 42e26b80
Revises: 58c50ef19f08
Create Date: 2025-07-05 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '42e26b80'
down_revision = '58c50ef19f08'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add token_usage column to chat_message table
    op.add_column('chat_message', sa.Column('token_usage', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    # Remove token_usage column from chat_message table
    op.drop_column('chat_message', 'token_usage')