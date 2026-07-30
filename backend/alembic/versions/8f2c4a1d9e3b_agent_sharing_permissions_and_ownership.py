"""agent sharing permissions and ownership

Revision ID: 8f2c4a1d9e3b
Revises: 01c63968ff8f
Create Date: 2026-06-11

Adds per-share permission levels (EDITOR/VIEWER) to persona shares, group
ownership + org-wide permission level to persona, and switches the owner FK
to SET NULL so deleting a user orphans shared personas instead of cascading.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8f2c4a1d9e3b"
down_revision = "01c63968ff8f"
branch_labels = None
depends_on = None

# Lightweight table reference for the backfill DML — avoids importing ORM models.
persona__user_group_table = sa.table(
    "persona__user_group",
    sa.column("permission", sa.String),
)


def upgrade() -> None:
    op.add_column(
        "persona__user",
        sa.Column("permission", sa.String(), nullable=False, server_default="VIEWER"),
    )
    op.add_column(
        "persona__user_group",
        sa.Column("permission", sa.String(), nullable=False, server_default="VIEWER"),
    )
    # Group shares previously granted group members edit access via
    # _add_user_filters; keep that for existing rows. New rows default VIEWER.
    op.execute(persona__user_group_table.update().values(permission="EDITOR"))
    op.add_column(
        "persona",
        sa.Column("owner_group_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "persona",
        sa.Column(
            "public_permission", sa.String(), nullable=False, server_default="VIEWER"
        ),
    )
    op.create_foreign_key(
        "persona_owner_group_id_fkey",
        "persona",
        "user_group",
        ["owner_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("persona__user_fk", "persona", type_="foreignkey")
    op.create_foreign_key(
        "persona__user_fk",
        "persona",
        "user",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_persona_single_owner",
        "persona",
        "user_id IS NULL OR owner_group_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_persona_single_owner", "persona", type_="check")
    op.drop_constraint("persona__user_fk", "persona", type_="foreignkey")
    # Faithful restore: the original FK (b156fa702355) has no ondelete
    op.create_foreign_key(
        "persona__user_fk",
        "persona",
        "user",
        ["user_id"],
        ["id"],
    )
    op.drop_constraint("persona_owner_group_id_fkey", "persona", type_="foreignkey")
    op.drop_column("persona", "public_permission")
    op.drop_column("persona", "owner_group_id")
    op.drop_column("persona__user_group", "permission")
    op.drop_column("persona__user", "permission")
