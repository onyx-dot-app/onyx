"""add model_configuration_id to user_usage

Revision ID: 0437efc9ed01
Revises: 70aed6c27639
Create Date: 2026-10-30 12:00:00.000000

Usage rows record the saved model configuration a call ran, so per-model spend
limits can count usage by id rather than by (model name, provider type), which
two configurations can share.

The column has no foreign key: configuration ids are never reused, so a stale
id is harmless, and a delete must not rewrite usage rows.

The backfill covers the current UTC month and the current UTC week (from
Monday), whichever starts first: the windows the spend periods can still
enforce. It fills a row only when its (model, provider) matches exactly one
configuration; ambiguous rows stay NULL. The dedup indexes gain the column in
the next revision, built CONCURRENTLY.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0437efc9ed01"
down_revision = "70aed6c27639"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_usage",
        sa.Column("model_configuration_id", sa.Integer(), nullable=True),
    )
    # Release the ACCESS EXCLUSIVE lock from add_column before the backfill
    # scans the table. env.py commits the next autobegun transaction.
    op.get_bind().commit()
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
              AND u.window_start >= LEAST(
                  date_trunc('month', now() AT TIME ZONE 'UTC'),
                  date_trunc('week', now() AT TIME ZONE 'UTC')
              ) AT TIME ZONE 'UTC'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("user_usage", "model_configuration_id")
