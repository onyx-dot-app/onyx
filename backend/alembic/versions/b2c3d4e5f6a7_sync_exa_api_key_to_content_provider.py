"""sync exa api key to content provider

Revision ID: b2c3d4e5f6a7
Revises: a3c1a7904cd0
Create Date: 2026-01-09 15:00:00.000000

"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a3c1a7904cd0"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Exa uses a shared API key between search and content providers.
    # For existing Exa search providers with API keys, create the corresponding
    # content provider if it doesn't exist yet.
    connection = op.get_bind()

    # Check if Exa search provider exists with an API key
    result = connection.execute(
        text(
            """
            SELECT api_key FROM internet_search_provider
            WHERE provider_type = 'exa' AND api_key IS NOT NULL
            LIMIT 1
            """
        )
    )
    row = result.fetchone()

    if row:
        api_key = row[0]
        # Check if Exa content provider already exists
        existing = connection.execute(
            text(
                """
                SELECT id FROM internet_content_provider
                WHERE provider_type = 'exa'
                LIMIT 1
                """
            )
        )
        if existing.fetchone() is None:
            # Create Exa content provider with the shared key
            connection.execute(
                text(
                    """
                    INSERT INTO internet_content_provider
                    (name, provider_type, api_key, is_active)
                    VALUES ('Exa', 'exa', :api_key, false)
                    """
                ),
                {"api_key": api_key},
            )


def downgrade() -> None:
    # We don't remove the content provider on downgrade since it may have been
    # intentionally created by the user. The migration is purely additive for
    # backwards compatibility.
    pass
