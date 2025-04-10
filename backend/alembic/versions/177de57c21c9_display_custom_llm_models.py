"""display custom llm models

Revision ID: 177de57c21c9
Revises: 4ee1287bd26a
Create Date: 2024-11-21 11:49:04.488677

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import and_

revision = "177de57c21c9"
down_revision = "4ee1287bd26a"
branch_labels = None
depends_on = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    llm_provider = sa.table(
        "llm_provider",
        sa.column("id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column("model_names", postgresql.ARRAY(sa.String)),
        sa.column("display_model_names", postgresql.ARRAY(sa.String)),
    )

    excluded_providers = ["openai", "bedrock", "anthropic", "azure"]

    providers_to_update = sa.select(
        llm_provider.c.id,
        llm_provider.c.model_names,
        llm_provider.c.display_model_names,
    ).where(
        and_(
            ~llm_provider.c.provider.in_(excluded_providers),
            llm_provider.c.model_names.isnot(None),
        )
    )

    results = conn.execute(providers_to_update).fetchall()

    for provider_id, model_names, display_model_names in results:
        if display_model_names is None:
            display_model_names = []

        combined_model_names = list(set(display_model_names + model_names))
        update_stmt = (
            llm_provider.update()
            .where(llm_provider.c.id == provider_id)
            .values(display_model_names=combined_model_names)
        )
        conn.execute(update_stmt)


def downgrade() -> None:
    pass
