"""embedding provider by provider type

Revision ID: f17bf3b0d9f1
Revises: 351faebd379d
Create Date: 2024-08-21 13:13:31.120460

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f17bf3b0d9f1"
down_revision = "351faebd379d"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Add provider_type column to embedding_provider
    op.add_column(
        "embedding_provider",
        sa.Column("provider_type", sa.String(50), nullable=True),
    )

    # Update provider_type with existing name values
    op.execute("UPDATE embedding_provider SET provider_type = UPPER(name)")

    # Make provider_type not nullable
    op.alter_column("embedding_provider", "provider_type", nullable=False)

    # Drop the foreign key constraint in embedding_model table
    op.drop_constraint(
        "fk_embedding_model_cloud_provider", "embedding_model", type_="foreignkey"
    )

    # Drop the existing primary key constraint
    op.drop_constraint("embedding_provider_pkey", "embedding_provider", type_="primary")

    # Create a new primary key constraint on provider_type
    op.create_primary_key(
        "embedding_provider_pkey", "embedding_provider", ["provider_type"]
    )

    # Add provider_type column to embedding_model
    op.add_column(
        "embedding_model",
        sa.Column("provider_type", sa.String(50), nullable=True),
    )

    # Update provider_type for existing embedding models
    op.execute(
        """
        UPDATE embedding_model
        SET provider_type = (
            SELECT provider_type
            FROM embedding_provider
            WHERE embedding_provider.id = embedding_model.cloud_provider_id
        )
    """
    )

    # Drop the old id column from embedding_provider
    op.drop_column("embedding_provider", "id")

    # Drop the name column from embedding_provider
    op.drop_column("embedding_provider", "name")

    # Drop the default_model_id column from embedding_provider
    op.drop_column("embedding_provider", "default_model_id")

    # Drop the old cloud_provider_id column from embedding_model
    op.drop_column("embedding_model", "cloud_provider_id")

    # Create the new foreign key constraint
    op.create_foreign_key(
        "fk_embedding_model_cloud_provider",
        "embedding_model",
        "embedding_provider",
        ["provider_type"],
        ["provider_type"],
    )


def downgrade() -> None:
    # Drop the foreign key constraint in embedding_model table
    op.drop_constraint(
        "fk_embedding_model_cloud_provider", "embedding_model", type_="foreignkey"
    )

    # Add back the cloud_provider_id column to embedding_model
    op.add_column(
        "embedding_model", sa.Column("cloud_provider_id", sa.Integer(), nullable=True)
    )
    op.add_column("embedding_provider", sa.Column("id", sa.Integer(), nullable=True))

    # Assign incrementing IDs to embedding providers
    op.execute(
        """
        CREATE SEQUENCE IF NOT EXISTS embedding_provider_id_seq;"""
    )
    op.execute(
        """
        UPDATE embedding_provider SET id = nextval('embedding_provider_id_seq');
    """
    )

    # Update cloud_provider_id based on provider_type
    op.execute(
        """
        UPDATE embedding_model
        SET cloud_provider_id = CASE
            WHEN provider_type IS NULL THEN NULL
            ELSE (
                SELECT id
                FROM embedding_provider
                WHERE embedding_provider.provider_type = embedding_model.provider_type
            )
        END
    """
    )

    # Drop the provider_type column from embedding_model
    op.drop_column("embedding_model", "provider_type")

    # Add back the columns to embedding_provider
    op.add_column("embedding_provider", sa.Column("name", sa.String(50), nullable=True))
    op.add_column(
        "embedding_provider", sa.Column("default_model_id", sa.Integer(), nullable=True)
    )

    # Drop the existing primary key constraint on provider_type
    op.drop_constraint("embedding_provider_pkey", "embedding_provider", type_="primary")

    # Create the original primary key constraint on id
    op.create_primary_key("embedding_provider_pkey", "embedding_provider", ["id"])

    # Update name with existing provider_type values
    op.execute(
        """
        UPDATE embedding_provider
        SET name = CASE
            WHEN provider_type = 'OPENAI' THEN 'OpenAI'
            WHEN provider_type = 'COHERE' THEN 'Cohere'
            WHEN provider_type = 'GOOGLE' THEN 'Google'
            WHEN provider_type = 'VOYAGE' THEN 'Voyage'
            ELSE provider_type
        END
    """
    )

    # Drop the provider_type column from embedding_provider
    op.drop_column("embedding_provider", "provider_type")

    # Recreate the foreign key constraint in embedding_model table
    op.create_foreign_key(
        "fk_embedding_model_cloud_provider",
        "embedding_model",
        "embedding_provider",
        ["cloud_provider_id"],
        ["id"],
    )

    # Recreate the foreign key constraint in embedding_model table
    op.create_foreign_key(
        "fk_embedding_provider_default_model",
        "embedding_provider",
        "embedding_model",
        ["default_model_id"],
        ["id"],
    )
