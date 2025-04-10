"""add_system_prompt_table

Revision ID: 90644d97dae8
Revises: 363e8c7b2339
Create Date: 2024-04-09 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90644d97dae8'
down_revision: Union[str, None] = '363e8c7b2339'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system_prompt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('contents', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_system_prompt_name')
    )


def downgrade() -> None:
    op.drop_table('system_prompt')
