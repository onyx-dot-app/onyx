"""add sync_attempt_error

Revision ID: c3e8a1f5d702
Revises: b20bded0b4f3
Create Date: 2026-11-04 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3e8a1f5d702"
down_revision = "b20bded0b4f3"
branch_labels = None
depends_on = None

_TABLE = "sync_attempt_error"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "external_group_sync_attempt_id",
            sa.Integer(),
            sa.ForeignKey(
                "external_group_permission_sync_attempt.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "connector_credential_pair_id",
            sa.Integer(),
            sa.ForeignKey("connector_credential_pair.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_kind",
            sa.Enum("user", "group", name="syncentitykind", native_enum=False),
            nullable=False,
        ),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("entity_name", sa.String(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column(
            "time_created",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "resolved_reason",
            sa.Enum(
                "without_retry",
                name="syncattempterrorresolvedreason",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sync_attempt_error_cc_pair_attempt",
        _TABLE,
        ["connector_credential_pair_id", "external_group_sync_attempt_id"],
    )
    op.create_index(
        "ix_sync_attempt_error_attempt",
        _TABLE,
        ["external_group_sync_attempt_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_attempt_error_attempt", table_name=_TABLE)
    op.drop_index("ix_sync_attempt_error_cc_pair_attempt", table_name=_TABLE)
    op.drop_table(_TABLE)
