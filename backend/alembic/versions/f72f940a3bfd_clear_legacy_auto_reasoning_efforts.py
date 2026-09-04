"""clear legacy auto reasoning efforts

ReasoningEffort no longer has an AUTO member. Its four columns are string-backed
enums, so a row still holding "auto" would fail to load. NULL already means
unpinned, so clear any such value.

Revision ID: f72f940a3bfd
Revises: 287021f3b46c
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f72f940a3bfd"
down_revision = "287021f3b46c"
branch_labels = None
depends_on = None

LEGACY_AUTO = "auto"

# Every column typed as Enum(ReasoningEffort, native_enum=False).
REASONING_EFFORT_COLUMNS = (
    ("chat_session", "reasoning_effort_override"),
    ("user", "reasoning_effort_default"),
    ("model_configuration", "reasoning_effort_max"),
    ("model_configuration", "reasoning_effort_default"),
)


def upgrade() -> None:
    for table_name, column_name in REASONING_EFFORT_COLUMNS:
        table = sa.table(table_name, sa.column(column_name, sa.String))
        column = table.c[column_name]
        op.execute(
            sa.update(table).where(column == LEGACY_AUTO).values({column_name: None})
        )


def downgrade() -> None:
    # "auto" and NULL both meant unpinned, so there is nothing to restore.
    pass
