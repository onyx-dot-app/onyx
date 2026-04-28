"""add index_attempt_stage_metric table

Revision ID: 14162713706c
Revises: a7c3e2b1d4f8
Create Date: 2026-04-26 18:51:46.914793

"""

from alembic import op
import sqlalchemy as sa

revision = "14162713706c"
down_revision = "a7c3e2b1d4f8"
branch_labels = None
depends_on = None


# Stage names are stored as VARCHAR (native_enum=False) to match the
# codebase-wide convention; new stages can be added without an enum-altering
# migration. Keep this list in sync with onyx.db.index_attempt_metrics.IndexAttemptStage.
_INDEX_ATTEMPT_STAGE_VALUES = (
    "CONNECTOR_VALIDATION",
    "PERMISSION_VALIDATION",
    "CHECKPOINT_LOAD",
    "CONNECTOR_FETCH",
    "HIERARCHY_UPSERT",
    "DOC_BATCH_STORE",
    "DOC_BATCH_ENQUEUE",
    "QUEUE_WAIT",
    "DOCPROCESSING_SETUP",
    "BATCH_LOAD",
    "DOC_DB_PREPARE",
    "IMAGE_PROCESSING",
    "CHUNKING",
    "CONTEXTUAL_RAG",
    "EMBEDDING",
    "VECTOR_DB_WRITE",
    "POST_INDEX_DB_UPDATE",
    "COORDINATION_UPDATE",
    "BATCH_TOTAL",
)


def upgrade() -> None:
    op.create_table(
        "index_attempt_stage_metric",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "index_attempt_id",
            sa.Integer(),
            sa.ForeignKey("index_attempt.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "stage",
            sa.Enum(
                *_INDEX_ATTEMPT_STAGE_VALUES,
                name="indexattemptstage",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("event_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "total_duration_ms",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "m2_duration_ms",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("min_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("max_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("time_first_event", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_last_event", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "index_attempt_id",
            "stage",
            name="uq_index_attempt_stage_metric_attempt_stage",
        ),
    )


def downgrade() -> None:
    op.drop_table("index_attempt_stage_metric")
