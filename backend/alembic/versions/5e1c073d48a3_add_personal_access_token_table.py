"""add_personal_access_token_table

Revision ID: 5e1c073d48a3
Revises: 09995b8811eb
Create Date: 2025-10-30 17:30:24.308521

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "5e1c073d48a3"
down_revision = "09995b8811eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create personal_access_token table
    op.create_table(
        "personal_access_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hashed_token", sa.String(length=64), nullable=False),
        sa.Column("token_display", sa.String(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "is_revoked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hashed_token"),
    )

    # Create indexes
    op.create_index(
        "ix_personal_access_token_expires_at",
        "personal_access_token",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_pat_user_created",
        "personal_access_token",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes first
    op.drop_index("ix_pat_user_created", table_name="personal_access_token")
    op.drop_index(
        "ix_personal_access_token_expires_at", table_name="personal_access_token"
    )

    # Drop table
    op.drop_table("personal_access_token")
