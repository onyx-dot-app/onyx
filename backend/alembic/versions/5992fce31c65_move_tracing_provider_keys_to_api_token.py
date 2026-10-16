"""move tracing provider keys to api_token

Revision ID: 5992fce31c65
Revises: 783fc0761f69
Create Date: 2026-10-16 03:00:00.000000

Each stored key becomes its own api_token row; nothing is merged. The
encrypted bytes are copied as they are, so no value is decrypted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "5992fce31c65"
down_revision = "783fc0761f69"
branch_labels = None
depends_on = None

# (table, primary key column, platform SQL, base URL SQL, extra row filter)
_TABLES: list[tuple[str, str, str, str, str]] = [
    ("tracing_provider_config", "id", "provider_type", "NULL", ""),
]


def upgrade() -> None:
    conn = op.get_bind()
    for table, pk, platform_sql, base_url_sql, row_filter in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "api_token_id",
                sa.Integer(),
                sa.ForeignKey("api_token.id", ondelete="RESTRICT"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_api_token_id", table, ["api_token_id"])

        rows = conn.execute(
            sa.text(
                f"SELECT {pk}::text AS pk, {platform_sql} AS platform, "
                f"{base_url_sql} AS base_url, api_key FROM {table} "
                f"WHERE api_key IS NOT NULL {row_filter}"
            )
        ).fetchall()
        for row in rows:
            token_id = conn.execute(
                sa.text(
                    "INSERT INTO api_token (platform, value, base_url) "
                    "VALUES (:platform, :value, :base_url) RETURNING id"
                ),
                {
                    "platform": row.platform,
                    "value": row.api_key,
                    "base_url": row.base_url,
                },
            ).scalar_one()
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET api_token_id = :token_id "
                    f"WHERE {pk}::text = :pk"
                ),
                {"token_id": token_id, "pk": row.pk},
            )

        op.drop_column(table, "api_key")


def downgrade() -> None:
    conn = op.get_bind()
    # The tokens stay: another feature may share them. The cleanup task (or
    # the api_token revision's downgrade) removes any left unused.
    for table, _pk, _platform_sql, _base_url_sql, _row_filter in _TABLES:
        op.add_column(table, sa.Column("api_key", sa.LargeBinary(), nullable=True))
        conn.execute(
            sa.text(
                f"UPDATE {table} SET api_key = api_token.value FROM api_token "
                f"WHERE {table}.api_token_id = api_token.id"
            )
        )
        op.drop_index(f"ix_{table}_api_token_id", table_name=table)
        op.drop_column(table, "api_token_id")
