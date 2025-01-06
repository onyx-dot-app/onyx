"""embedding model -> search settings

Revision ID: 1f60f60c3401
Revises: f17bf3b0d9f1
Create Date: 2024-08-25 12:39:51.731632

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from onyx.configs.chat_configs import NUM_POSTPROCESSED_RESULTS

# revision identifiers, used by Alembic.
revision = "1f60f60c3401"
down_revision = "f17bf3b0d9f1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint(
        "index_attempt__embedding_model_fk", "index_attempt", type_="foreignkey"
    )
    # Rename the table
    op.rename_table("embedding_model", "search_settings")

    # Add new columns
    op.add_column(
        "search_settings",
        sa.Column(
            "multipass_indexing", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "multilingual_expansion",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "disable_rerank_for_streaming",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "search_settings", sa.Column("rerank_model_name", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings", sa.Column("rerank_provider_type", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings", sa.Column("rerank_api_key", sa.String(), nullable=True)
    )
    op.add_column(
        "search_settings",
        sa.Column(
            "num_rerank",
            sa.Integer(),
            nullable=False,
            server_default=str(NUM_POSTPROCESSED_RESULTS),
        ),
    )

    # Add the new column as nullable initially
    op.add_column(
        "index_attempt", sa.Column("search_settings_id", sa.Integer(), nullable=True)
    )

    # Populate the new column with data from the existing embedding_model_id
    op.execute("UPDATE index_attempt SET search_settings_id = embedding_model_id")

    # Create the foreign key constraint
    op.create_foreign_key(
        "fk_index_attempt_search_settings",
        "index_attempt",
        "search_settings",
        ["search_settings_id"],
        ["id"],
    )

    # Make the new column non-nullable
    op.alter_column("index_attempt", "search_settings_id", nullable=False)

    # Drop the old embedding_model_id column
    op.drop_column("index_attempt", "embedding_model_id")


def downgrade() -> None:
    # Add back the embedding_model_id column
    op.add_column(
        "index_attempt", sa.Column("embedding_model_id", sa.Integer(), nullable=True)
    )

    # Populate the old column with data from search_settings_id
    op.execute("UPDATE index_attempt SET embedding_model_id = search_settings_id")

    # Make the old column non-nullable
    op.alter_column("index_attempt", "embedding_model_id", nullable=False)

    # Drop the foreign key constraint
    op.drop_constraint(
        "fk_index_attempt_search_settings", "index_attempt", type_="foreignkey"
    )

    # Drop the new search_settings_id column
    op.drop_column("index_attempt", "search_settings_id")

    # Rename the table back
    op.rename_table("search_settings", "embedding_model")

    # Remove added columns
    op.drop_column("embedding_model", "num_rerank")
    op.drop_column("embedding_model", "rerank_api_key")
    op.drop_column("embedding_model", "rerank_provider_type")
    op.drop_column("embedding_model", "rerank_model_name")
    op.drop_column("embedding_model", "disable_rerank_for_streaming")
    op.drop_column("embedding_model", "multilingual_expansion")
    op.drop_column("embedding_model", "multipass_indexing")

    op.create_foreign_key(
        "index_attempt__embedding_model_fk",
        "index_attempt",
        "embedding_model",
        ["embedding_model_id"],
        ["id"],
    )
