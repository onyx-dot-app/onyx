"""Add langflow_file_node table

Revision ID: 54f3af073585
Revises: 5cc54b4cc28b
Create Date: 2025-11-01 17:29:17.548145

"""
from alembic import op
import sqlalchemy as sa


revision = '54f3af073585'
down_revision = '5cc54b4cc28b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('langflow_file_node',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('file_node_id', sa.String(), nullable=False),
    sa.Column('persona_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['persona_id'], ['persona.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('langflow_file_node')
