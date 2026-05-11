"""contextual_rag_model_configuration_fk

Revision ID: 4ff2545411ad
Revises: f0db5f1c6370
Create Date: 2026-05-06 11:09:28.087586

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4ff2545411ad"
down_revision = "f3c9e59c3b07"
branch_labels = None
depends_on = None

_search_settings = sa.table(
    "search_settings",
    sa.column("contextual_rag_model_configuration_id", sa.Integer()),
    sa.column("contextual_rag_llm_name", sa.String()),
    sa.column("contextual_rag_llm_provider", sa.String()),
)
_llm_provider = sa.table(
    "llm_provider",
    sa.column("id", sa.Integer()),
    sa.column("name", sa.String()),
)
_model_configuration = sa.table(
    "model_configuration",
    sa.column("id", sa.Integer()),
    sa.column("llm_provider_id", sa.Integer()),
    sa.column("name", sa.String()),
)


def upgrade() -> None:
    # 1. Add FK column
    op.add_column(
        "search_settings",
        sa.Column("contextual_rag_model_configuration_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_search_settings_contextual_rag_model_configuration",
        "search_settings",
        "model_configuration",
        ["contextual_rag_model_configuration_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Data migration: populate FK from the old string columns
    op.execute(
        sa.update(_search_settings)
        .values(contextual_rag_model_configuration_id=_model_configuration.c.id)
        .where(
            _llm_provider.c.id == _model_configuration.c.llm_provider_id,
            _model_configuration.c.name == _search_settings.c.contextual_rag_llm_name,
            _llm_provider.c.name == _search_settings.c.contextual_rag_llm_provider,
            _search_settings.c.contextual_rag_llm_name.isnot(None),
            _search_settings.c.contextual_rag_llm_provider.isnot(None),
        )
    )

    # 3. Drop the string columns
    op.drop_column("search_settings", "contextual_rag_llm_name")
    op.drop_column("search_settings", "contextual_rag_llm_provider")


def downgrade() -> None:
    # Re-add string columns
    op.add_column(
        "search_settings",
        sa.Column("contextual_rag_llm_name", sa.String(), nullable=True),
    )
    op.add_column(
        "search_settings",
        sa.Column("contextual_rag_llm_provider", sa.String(), nullable=True),
    )

    # Back-fill string columns from FK
    op.execute(
        sa.update(_search_settings)
        .values(
            contextual_rag_llm_name=_model_configuration.c.name,
            contextual_rag_llm_provider=_llm_provider.c.name,
        )
        .where(
            _model_configuration.c.id
            == _search_settings.c.contextual_rag_model_configuration_id,
            _llm_provider.c.id == _model_configuration.c.llm_provider_id,
            _search_settings.c.contextual_rag_model_configuration_id.isnot(None),
        )
    )

    op.drop_constraint(
        "fk_search_settings_contextual_rag_model_configuration",
        "search_settings",
        type_="foreignkey",
    )
    op.drop_column("search_settings", "contextual_rag_model_configuration_id")
