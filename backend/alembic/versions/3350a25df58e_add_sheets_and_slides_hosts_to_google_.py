"""add sheets and slides hosts to google drive external apps

``upstream_url_patterns`` is snapshotted onto app rows at creation, so rows
that predate the Sheets/Slides hosts need them appended.

Revision ID: 3350a25df58e
Revises: c7f1a9d4e206
Create Date: 2026-08-12 16:13:59.650319

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3350a25df58e"
down_revision = "17135ac06582"
branch_labels = None
depends_on = None

_APP_TYPE = "GOOGLE_DRIVE"
_NEW_PATTERNS = [
    "https://sheets\\.googleapis\\.com/.*",
    "https://slides\\.googleapis\\.com/.*",
]


def upgrade() -> None:
    bind = op.get_bind()
    # The column is varchar[]; CAST keeps array_append/array_remove typed.
    for pattern in _NEW_PATTERNS:
        bind.execute(
            sa.text(
                "UPDATE external_app "
                "SET upstream_url_patterns = array_append("
                "    upstream_url_patterns, CAST(:pattern AS varchar)) "
                "WHERE app_type = :app_type "
                "AND NOT (:pattern = ANY(upstream_url_patterns))"
            ),
            {"pattern": pattern, "app_type": _APP_TYPE},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for pattern in _NEW_PATTERNS:
        bind.execute(
            sa.text(
                "UPDATE external_app "
                "SET upstream_url_patterns = array_remove("
                "    upstream_url_patterns, CAST(:pattern AS varchar)) "
                "WHERE app_type = :app_type"
            ),
            {"pattern": pattern, "app_type": _APP_TYPE},
        )
