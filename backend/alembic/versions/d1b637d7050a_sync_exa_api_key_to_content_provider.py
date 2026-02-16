"""sync_exa_api_key_to_content_provider

Revision ID: d1b637d7050a
Revises: d25168c2beee
Create Date: 2026-01-09 15:54:15.646249

"""

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "d1b637d7050a"
down_revision = "d25168c2beee"
branch_labels = None
depends_on = None


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
        # Create Exa content provider with the shared key
        connection.execute(
            text(
                """
                INSERT INTO internet_content_provider
                (name, provider_type, api_key, is_active)
                VALUES ('Exa', 'exa', :api_key, false)
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {"api_key": api_key},
        )


def downgrade() -> None:
    # Remove the Exa content provider that was created by this migration
    connection = op.get_bind()
    connection.execute(
        text(
            """
            DELETE FROM internet_content_provider
            WHERE provider_type = 'exa'
            """
        )
    )
