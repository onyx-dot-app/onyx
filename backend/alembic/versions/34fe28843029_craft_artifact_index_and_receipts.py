"""Craft artifact index columns and action receipts

The artifact table becomes the index the output panel renders from, with an
upsert key on (session, path). action_receipt records external actions with a
pending/confirmed/failed/unknown lifecycle for receipt cards.

Revision ID: 34fe28843029
Revises: 66a70ddc0652
Create Date: 2026-08-26

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "34fe28843029"
down_revision = "66a70ddc0652"
branch_labels = None
depends_on = None

# Non-native enums store member NAMES in a VARCHAR sized to the longest one.
# The original artifact.type was sized for six members (VARCHAR(8)), too narrow
# for DIRECTORY, so upgrade widens it to the full member set.
_ARTIFACT_TYPE_OLD = sa.Enum(
    "WEB_APP",
    "PPTX",
    "DOCX",
    "IMAGE",
    "MARKDOWN",
    "EXCEL",
    native_enum=False,
    name="artifacttype",
)
_ARTIFACT_TYPE_NEW = sa.Enum(
    "WEB_APP",
    "PPTX",
    "DOCX",
    "IMAGE",
    "MARKDOWN",
    "EXCEL",
    "PDF",
    "CSV",
    "CODE",
    "DIRECTORY",
    "AUDIO",
    "VIDEO",
    "ARCHIVE",
    "FILE",
    native_enum=False,
    name="artifacttype",
)
_RECEIPT_STATUS = sa.Enum(
    "PENDING",
    "CONFIRMED",
    "FAILED",
    "UNKNOWN",
    native_enum=False,
    name="receiptstatus",
)


def upgrade() -> None:
    op.alter_column(
        "artifact",
        "type",
        existing_type=_ARTIFACT_TYPE_OLD,
        type_=_ARTIFACT_TYPE_NEW,
        existing_nullable=False,
    )
    op.add_column("artifact", sa.Column("turn_index", sa.Integer(), nullable=True))
    op.add_column("artifact", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("artifact", sa.Column("content_hash", sa.String(), nullable=True))
    op.add_column(
        "artifact",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "artifact",
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("artifact", sa.Column("archive_file_id", sa.String(), nullable=True))
    op.create_index(
        "uq_artifact_session_path",
        "artifact",
        ["session_id", "path"],
        unique=True,
    )

    op.create_table(
        "action_receipt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gated_app_id", sa.Integer(), nullable=True),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("effect", sa.String(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("operation_key", sa.String(), nullable=True),
        sa.Column("status", _RECEIPT_STATUS, server_default="PENDING", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["build_session.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["gated_app_id"], ["gated_app.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["action_approval.approval_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_receipt_session_created",
        "action_receipt",
        ["session_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "uq_action_receipt_session_operation",
        "action_receipt",
        ["session_id", "operation_key"],
        unique=True,
        postgresql_where=sa.text("operation_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_action_receipt_session_operation", table_name="action_receipt")
    op.drop_index("ix_action_receipt_session_created", table_name="action_receipt")
    op.drop_table("action_receipt")
    op.drop_index("uq_artifact_session_path", table_name="artifact")
    op.drop_column("artifact", "archive_file_id")
    op.drop_column("artifact", "deleted")
    op.drop_column("artifact", "version")
    op.drop_column("artifact", "content_hash")
    op.drop_column("artifact", "size_bytes")
    op.drop_column("artifact", "turn_index")
    # type stays wide on downgrade: narrowing would fail on rows holding the
    # new values, and a wider varchar is harmless to the old code.
