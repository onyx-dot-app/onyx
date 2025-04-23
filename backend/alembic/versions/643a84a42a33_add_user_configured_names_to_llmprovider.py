"""Add user-configured names to LLMProvider

Revision ID: 643a84a42a33
Revises: 0a98909f2757
Create Date: 2024-05-07 14:54:55.493100

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "643a84a42a33"
down_revision = "0a98909f2757"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("llm_provider", sa.Column("provider", sa.String(), nullable=True))
    # move "name" -> "provider" to match the new schema
    op.execute("UPDATE llm_provider SET provider = name")
    # pretty up display name
    op.execute("UPDATE llm_provider SET name = 'OpenAI' WHERE name = 'openai'")
    op.execute("UPDATE llm_provider SET name = 'Anthropic' WHERE name = 'anthropic'")
    op.execute("UPDATE llm_provider SET name = 'Azure OpenAI' WHERE name = 'azure'")
    op.execute("UPDATE llm_provider SET name = 'AWS Bedrock' WHERE name = 'bedrock'")

    # update personas to use the new provider names
    op.execute(
        "UPDATE persona SET llm_model_provider_override = 'OpenAI' WHERE llm_model_provider_override = 'openai'"
    )
    op.execute(
        "UPDATE persona SET llm_model_provider_override = 'Anthropic' WHERE llm_model_provider_override = 'anthropic'"
    )
    op.execute(
        "UPDATE persona SET llm_model_provider_override = 'Azure OpenAI' WHERE llm_model_provider_override = 'azure'"
    )
    op.execute(
        "UPDATE persona SET llm_model_provider_override = 'AWS Bedrock' WHERE llm_model_provider_override = 'bedrock'"
    )


def downgrade() -> None:
    op.execute("UPDATE llm_provider SET name = provider")
    op.drop_column("llm_provider", "provider")
