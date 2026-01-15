"""Drop milestone table

Revision ID: b8c9d0e1f2a3
Revises: a2b3c4d5e6f7
Create Date: 2025-12-18

"""

from alembic import op
import sqlalchemy as sa
import fastapi_users_db_sqlalchemy
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("milestone")


def downgrade() -> None:
    op.create_table(
        "milestone",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_tracker", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type", name="uq_milestone_event_type"),
    )
