"""add_marketing_campaign_table

Revision ID: 07e326dc5c1f
Revises: dfbe9e93d3c7
Create Date: 2024-06-16 19:14:44.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "07e326dc5c1f"
down_revision = "dfbe9e93d3c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_campaign",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("image_content", sa.Text(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("time_created", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("time_updated", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    
    op.create_index("ix_marketing_campaign_user_id", "marketing_campaign", ["user_id"])
    op.create_index("ix_marketing_campaign_status", "marketing_campaign", ["status"])
    op.create_index("ix_marketing_campaign_deleted", "marketing_campaign", ["deleted"])


def downgrade() -> None:
    op.drop_index("ix_marketing_campaign_deleted", table_name="marketing_campaign")
    op.drop_index("ix_marketing_campaign_status", table_name="marketing_campaign")
    op.drop_index("ix_marketing_campaign_user_id", table_name="marketing_campaign")
    op.drop_table("marketing_campaign")
