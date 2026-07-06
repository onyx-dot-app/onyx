"""add port_orphan_candidate

Revision ID: 9d2e7f1a4c58
Revises: d49e41659191
Create Date: 2026-07-06 00:00:00.000000

Tracks documents deleted while a reindex port is running so the port attempt can
sweep any that a racing create-only write resurrected into the target index.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9d2e7f1a4c58"
down_revision = "d49e41659191"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_orphan_candidate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("search_settings_id", sa.Integer(), nullable=False),
        sa.Column("cc_pair_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["search_settings_id"],
            ["search_settings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cc_pair_id"],
            ["connector_credential_pair.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "search_settings_id",
            "cc_pair_id",
            "document_id",
            name="uq_port_orphan_candidate_settings_ccpair_doc",
        ),
    )
    # Index the cc_pair FK so ON DELETE CASCADE from a cc_pair doesn't seq-scan.
    op.create_index(
        op.f("ix_port_orphan_candidate_cc_pair_id"),
        "port_orphan_candidate",
        ["cc_pair_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_port_orphan_candidate_cc_pair_id"),
        table_name="port_orphan_candidate",
    )
    op.drop_table("port_orphan_candidate")
