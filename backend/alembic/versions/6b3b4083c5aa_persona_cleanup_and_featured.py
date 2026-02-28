"""persona cleanup and featured

Revision ID: 6b3b4083c5aa
Revises: 57122d037335
Create Date: 2026-02-26 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b3b4083c5aa"
down_revision = "57122d037335"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add featured column with nullable=True first
    op.add_column("persona", sa.Column("featured", sa.Boolean(), nullable=True))

    # Migrate data from is_default_persona to featured
    op.execute("UPDATE persona SET featured = is_default_persona")

    # Make featured non-nullable with default=False
    op.alter_column(
        "persona",
        "featured",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )

    # Drop is_default_persona column
    op.drop_column("persona", "is_default_persona")

    # Drop unused columns
    op.drop_column("persona", "num_chunks")
    op.drop_column("persona", "chunks_above")
    op.drop_column("persona", "chunks_below")
    op.drop_column("persona", "llm_relevance_filter")
    op.drop_column("persona", "llm_filter_extraction")
    op.drop_column("persona", "recency_bias")


def downgrade() -> None:
    # Add back recency_bias column
    op.add_column(
        "persona",
        sa.Column(
            "recency_bias",
            sa.VARCHAR(),
            nullable=False,
            server_default="base_decay",
        ),
    )

    # Add back llm_filter_extraction column
    op.add_column(
        "persona",
        sa.Column(
            "llm_filter_extraction",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Add back llm_relevance_filter column
    op.add_column(
        "persona",
        sa.Column(
            "llm_relevance_filter",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Add back chunks_below column
    op.add_column(
        "persona",
        sa.Column("chunks_below", sa.Integer(), nullable=False, server_default="0"),
    )

    # Add back chunks_above column
    op.add_column(
        "persona",
        sa.Column("chunks_above", sa.Integer(), nullable=False, server_default="0"),
    )

    # Add back num_chunks column
    op.add_column("persona", sa.Column("num_chunks", sa.Float(), nullable=True))

    # Add back is_default_persona column
    op.add_column(
        "persona",
        sa.Column(
            "is_default_persona",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Migrate data from featured to is_default_persona
    op.execute("UPDATE persona SET is_default_persona = featured")

    # Drop featured column
    op.drop_column("persona", "featured")
