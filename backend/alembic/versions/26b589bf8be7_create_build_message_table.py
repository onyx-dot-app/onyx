"""create_build_message_table

Revision ID: 26b589bf8be7
Revises: df6cbd9a37cc
Create Date: 2026-01-19 17:51:08.289325

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "26b589bf8be7"
down_revision = "df6cbd9a37cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reuse existing messagetype enum from chat_message table
    # Build messages only use: USER, ASSISTANT, SYSTEM
    # Note: The existing enum has uppercase values but MessageType in code uses lowercase
    # This works because SQLAlchemy handles the conversion when native_enum=False

    # Create build_message table
    op.create_table(
        "build_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.Enum(
                "SYSTEM",
                "USER",
                "ASSISTANT",
                "DANSWER",
                name="messagetype",
                create_type=False,
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create index for build_message
    op.create_index(
        "ix_build_message_session_created",
        "build_message",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Drop index
    op.drop_index("ix_build_message_session_created", table_name="build_message")

    # Drop table
    op.drop_table("build_message")
