"""create_artifact_table

Revision ID: a441232d9c5a
Revises: 484b9fa1ac89
Create Date: 2026-01-19 14:47:57.226496

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a441232d9c5a"
down_revision = "484b9fa1ac89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create artifact type enum
    artifact_type_enum = sa.Enum(
        "react_app",
        "pptx",
        "docx",
        "markdown",
        "excel",
        "image",
        name="artifacttype",
        native_enum=False,
    )

    # Create artifact table
    op.create_table(
        "artifact",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("build_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", artifact_type_enum, nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for artifact
    op.create_index(
        "ix_artifact_session_created",
        "artifact",
        ["session_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_artifact_type",
        "artifact",
        ["type"],
        unique=False,
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_artifact_type", table_name="artifact")
    op.drop_index("ix_artifact_session_created", table_name="artifact")

    # Drop table
    op.drop_table("artifact")

    # Drop enum
    sa.Enum(name="artifacttype").drop(op.get_bind(), checkfirst=True)
