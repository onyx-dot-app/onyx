"""optional llm provider name

Revision ID: f0db5f1c6370
Revises: b6c7d8e9f0a1
Create Date: 2026-05-05

"""

from alembic import op
import sqlalchemy as sa

revision = "f0db5f1c6370"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None

llm_provider_table = sa.table(
    "llm_provider",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("provider", sa.String),
)


def upgrade() -> None:
    op.alter_column("llm_provider", "name", nullable=True)
    op.drop_constraint("llm_provider_name_key", "llm_provider", type_="unique")


def downgrade() -> None:
    # Best-effort: fill NULLs with "__unnamed_<id>" before restoring NOT NULL + UNIQUE.
    # The "__unnamed_" prefix is distinct from any legitimate provider name, so it can
    # never collide with an existing named provider.
    op.execute(
        sa.update(llm_provider_table)
        .values(
            name=sa.func.concat(
                "__unnamed_",
                sa.cast(llm_provider_table.c.id, sa.String),
            )
        )
        .where(llm_provider_table.c.name.is_(None))
    )
    op.create_unique_constraint("llm_provider_name_key", "llm_provider", ["name"])
    op.alter_column("llm_provider", "name", nullable=False)
