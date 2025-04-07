"""pro search enabled field

Revision ID: 363e8c7b2339
Revises: 96ce93072209
Create Date: 2025-04-06 20:19:00.156165

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '363e8c7b2339'
down_revision = '96ce93072209'
branch_labels = None
depends_on = None


def upgrade() -> None:
     # Add pro_search_enabled column as nullable first
    op.add_column('persona', sa.Column('pro_search_enabled', sa.Boolean(), nullable=True))
    
    # Set default value for existing rows
    op.execute("UPDATE persona SET pro_search_enabled = false")
    
    # Make the column non-nullable with a default value
    op.alter_column('persona', 'pro_search_enabled',
                    existing_type=sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('false'))


def downgrade() -> None:
    op.drop_column('persona', 'pro_search_enabled') 
