"""Workspace SMTP

Revision ID: c19ab15b0364
Revises: 17ca0f0827de
Create Date: 2024-11-14 15:01:30.083414

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c19ab15b0364"
down_revision = "17ca0f0827de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "workspace_settings", sa.Column("smtp_server", sa.Text(), nullable=True)
    )
    op.add_column(
        "workspace_settings", sa.Column("smtp_port", sa.Integer(), nullable=True)
    )
    op.add_column(
        "workspace_settings", sa.Column("smtp_username", sa.Text(), nullable=True)
    )
    op.add_column(
        "workspace_settings", sa.Column("smtp_password", sa.Text(), nullable=True)
    )
    op.add_column("workspace", sa.Column("brand_color", sa.Text(), nullable=True))
    op.add_column("workspace", sa.Column("secondary_color", sa.Text(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("workspace_settings", "smtp_password")
    op.drop_column("workspace_settings", "smtp_username")
    op.drop_column("workspace_settings", "smtp_port")
    op.drop_column("workspace_settings", "smtp_server")
    op.drop_column("workspace", "secondary_color")
    op.drop_column("workspace", "brand_color")
    # ### end Alembic commands ###
