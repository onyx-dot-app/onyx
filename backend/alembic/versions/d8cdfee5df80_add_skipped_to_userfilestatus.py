"""add skipped to userfilestatus

Revision ID: d8cdfee5df80
Revises: 1d78c0ca7853
Create Date: 2026-04-01 10:47:12.593950

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d8cdfee5df80"
down_revision = "1d78c0ca7853"
branch_labels = None
depends_on = None


TABLE = "user_file"
COLUMN = "status"
CONSTRAINT_NAME = "ck_user_file_status"

OLD_VALUES = ("PROCESSING", "INDEXING", "COMPLETED", "FAILED", "CANCELED", "DELETING")
NEW_VALUES = (
    "PROCESSING",
    "INDEXING",
    "COMPLETED",
    "SKIPPED",
    "FAILED",
    "CANCELED",
    "DELETING",
)


def _drop_status_check_constraint() -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_check_constraints(TABLE):
        if COLUMN in constraint.get("sqltext", ""):
            constraint_name = constraint["name"]
            if constraint_name is not None:
                op.drop_constraint(constraint_name, TABLE, type_="check")


def upgrade() -> None:
    _drop_status_check_constraint()
    in_clause = ", ".join(f"'{v}'" for v in NEW_VALUES)
    op.create_check_constraint(CONSTRAINT_NAME, TABLE, f"{COLUMN} IN ({in_clause})")


def downgrade() -> None:
    op.execute(f"UPDATE {TABLE} SET {COLUMN} = 'COMPLETED' WHERE {COLUMN} = 'SKIPPED'")
    _drop_status_check_constraint()
    in_clause = ", ".join(f"'{v}'" for v in OLD_VALUES)
    op.create_check_constraint(CONSTRAINT_NAME, TABLE, f"{COLUMN} IN ({in_clause})")
