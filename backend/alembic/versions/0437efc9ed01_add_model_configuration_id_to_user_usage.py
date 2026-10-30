"""add model_configuration_id to user_usage

Revision ID: 0437efc9ed01
Revises: b7d2e4f1a9c3
Create Date: 2026-10-30 12:00:00.000000

Usage rows record the saved model configuration a call ran, so per-model spend
limits can count usage by id rather than by (model name, provider type), which
two configurations can share.

The backfill covers the current UTC calendar month only: the longest spend
period, so older rows never affect enforcement. It fills a row only when its
(model, provider) matches exactly one configuration; ambiguous rows stay NULL.
The dedup indexes gain the column in the next revision, built CONCURRENTLY.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0437efc9ed01"
down_revision = "b7d2e4f1a9c3"
branch_labels = None
depends_on = None

FK_NAME = "fk_user_usage_model_configuration_id"


def upgrade() -> None:
    op.add_column(
        "user_usage",
        sa.Column("model_configuration_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        FK_NAME,
        "user_usage",
        "model_configuration",
        ["model_configuration_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        sa.text(
            """
            UPDATE user_usage AS u
            SET model_configuration_id = unique_model.id
            FROM (
                SELECT mc.name, p.provider, MIN(mc.id) AS id
                FROM model_configuration AS mc
                JOIN llm_provider AS p ON p.id = mc.llm_provider_id
                GROUP BY mc.name, p.provider
                HAVING COUNT(*) = 1
            ) AS unique_model
            WHERE u.model = unique_model.name
              AND u.provider = unique_model.provider
              AND u.model_configuration_id IS NULL
              AND u.window_start >= date_trunc('month', now() AT TIME ZONE 'UTC')
                  AT TIME ZONE 'UTC'
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(FK_NAME, "user_usage", type_="foreignkey")
    op.drop_column("user_usage", "model_configuration_id")
