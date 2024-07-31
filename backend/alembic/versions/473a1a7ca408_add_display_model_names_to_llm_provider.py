"""Add display_model_names to llm_provider

Revision ID: 473a1a7ca408
Revises: 325975216eb3
Create Date: 2024-07-25 14:31:02.002917

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "473a1a7ca408"
down_revision = "325975216eb3"
branch_labels: None = None
depends_on: None = None

default_models_by_provider = {
    "openai": ["gpt-4", "gpt-4o", "gpt-4o-mini"],
    "bedrock": [
        "meta.llama3-1-70b-instruct-v1:0",
        "meta.llama3-1-8b-instruct-v1:0",
        "anthropic.claude-3-opus-20240229-v1:0",
        "mistral.mistral-large-2402-v1:0",
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
    ],
    "anthropic": ["claude-3-opus-20240229", "claude-3-5-sonnet-20240620"],
}


def upgrade() -> None:
    op.add_column(
        "llm_provider",
        sa.Column("display_model_names", postgresql.ARRAY(sa.String()), nullable=True),
    )

    connection = op.get_bind()
    for provider, models in default_models_by_provider.items():
        connection.execute(
            sa.text(
                "UPDATE llm_provider SET display_model_names = :models WHERE provider = :provider"
            ),
            {"models": models, "provider": provider},
        )


def downgrade() -> None:
    op.drop_column("llm_provider", "display_model_names")
