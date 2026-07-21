"""replace external-app approval targets with a polymorphic gated_app

The approval pipeline (per-action policy, approval rows, scheduled-task
pre-approvals) attributed a gated request to an ``external_app`` row. Introduce a
polymorphic ``gated_app`` identity table — one row per external app or MCP
server — and repoint every consumer at a single ``gated_app_id`` FK, so a new
gated-target catalog adds one column to ``gated_app`` instead of a column to
every consumer table. ``external_app_policy`` becomes ``gated_action_policy``.

Revision ID: bc9e56f2fb96
Revises: 565c5b57a573
Create Date: 2026-07-17 14:10:36.718336

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "bc9e56f2fb96"
down_revision = "565c5b57a573"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- polymorphic identity table -------------------------------------
    # The target's kind is derived from which FK is populated; no stored
    # discriminator to keep consistent.
    op.create_table(
        "gated_app",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_app_id", sa.Integer(), nullable=True),
        sa.Column("mcp_server_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["external_app_id"], ["external_app.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_server.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_app_id", name="uq_gated_app_external_app"),
        sa.UniqueConstraint("mcp_server_id", name="uq_gated_app_mcp_server"),
        sa.CheckConstraint(
            "num_nonnulls(external_app_id, mcp_server_id) = 1",
            name="ck_gated_app_single_target",
        ),
    )
    # One identity row per existing target so current policy / approval /
    # pre-approval rows can be repointed. New targets get theirs lazily.
    op.execute("INSERT INTO gated_app (external_app_id) SELECT id FROM external_app")
    op.execute("INSERT INTO gated_app (mcp_server_id) SELECT id FROM mcp_server")

    # --- external_app_policy -> gated_action_policy ---------------------
    op.rename_table("external_app_policy", "gated_action_policy")
    op.add_column(
        "gated_action_policy",
        sa.Column("gated_app_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE gated_action_policy p SET gated_app_id = g.id "
        "FROM gated_app g WHERE g.external_app_id = p.external_app_id"
    )
    op.alter_column("gated_action_policy", "gated_app_id", nullable=False)
    op.drop_constraint(
        "uq_external_app_policy_app_action", "gated_action_policy", type_="unique"
    )
    op.drop_constraint(
        "external_app_policy_external_app_id_fkey",
        "gated_action_policy",
        type_="foreignkey",
    )
    op.drop_column("gated_action_policy", "external_app_id")
    op.create_foreign_key(
        "gated_action_policy_gated_app_id_fkey",
        "gated_action_policy",
        "gated_app",
        ["gated_app_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_gated_action_policy",
        "gated_action_policy",
        ["gated_app_id", "action_id"],
    )

    # --- action_approval ------------------------------------------------
    op.add_column(
        "action_approval", sa.Column("gated_app_id", sa.Integer(), nullable=True)
    )
    op.execute(
        "UPDATE action_approval a SET gated_app_id = g.id "
        "FROM gated_app g WHERE g.external_app_id = a.external_app_id"
    )
    op.drop_constraint(
        "fk_action_approval_external_app_id", "action_approval", type_="foreignkey"
    )
    op.drop_column("action_approval", "external_app_id")
    op.create_foreign_key(
        "fk_action_approval_gated_app_id",
        "action_approval",
        "gated_app",
        ["gated_app_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- scheduled_task_pre_approved_app --------------------------------
    op.add_column(
        "scheduled_task_pre_approved_app",
        sa.Column("gated_app_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE scheduled_task_pre_approved_app s SET gated_app_id = g.id "
        "FROM gated_app g WHERE g.external_app_id = s.external_app_id"
    )
    op.alter_column("scheduled_task_pre_approved_app", "gated_app_id", nullable=False)
    op.drop_constraint(
        "uq_scheduled_task_pre_approved_app",
        "scheduled_task_pre_approved_app",
        type_="unique",
    )
    op.drop_constraint(
        "scheduled_task_pre_approved_app_external_app_id_fkey",
        "scheduled_task_pre_approved_app",
        type_="foreignkey",
    )
    op.drop_column("scheduled_task_pre_approved_app", "external_app_id")
    op.create_foreign_key(
        "scheduled_task_pre_approved_app_gated_app_id_fkey",
        "scheduled_task_pre_approved_app",
        "gated_app",
        ["gated_app_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_scheduled_task_pre_approved_app",
        "scheduled_task_pre_approved_app",
        ["scheduled_task_id", "gated_app_id"],
    )


def downgrade() -> None:
    # Backfills read from gated_app, so it is dropped last. MCP-server targets
    # have no pre-gated representation: their approval rows null out, their
    # policy / pre-approval rows are dropped.

    # --- scheduled_task_pre_approved_app --------------------------------
    op.add_column(
        "scheduled_task_pre_approved_app",
        sa.Column("external_app_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE scheduled_task_pre_approved_app s SET external_app_id = "
        "g.external_app_id FROM gated_app g WHERE g.id = s.gated_app_id"
    )
    op.drop_constraint(
        "uq_scheduled_task_pre_approved_app",
        "scheduled_task_pre_approved_app",
        type_="unique",
    )
    op.drop_constraint(
        "scheduled_task_pre_approved_app_gated_app_id_fkey",
        "scheduled_task_pre_approved_app",
        type_="foreignkey",
    )
    op.drop_column("scheduled_task_pre_approved_app", "gated_app_id")
    op.execute(
        "DELETE FROM scheduled_task_pre_approved_app WHERE external_app_id IS NULL"
    )
    op.alter_column(
        "scheduled_task_pre_approved_app", "external_app_id", nullable=False
    )
    op.create_foreign_key(
        "scheduled_task_pre_approved_app_external_app_id_fkey",
        "scheduled_task_pre_approved_app",
        "external_app",
        ["external_app_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_scheduled_task_pre_approved_app",
        "scheduled_task_pre_approved_app",
        ["scheduled_task_id", "external_app_id"],
    )

    # --- action_approval ------------------------------------------------
    op.add_column(
        "action_approval",
        sa.Column("external_app_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE action_approval a SET external_app_id = g.external_app_id "
        "FROM gated_app g WHERE g.id = a.gated_app_id"
    )
    op.drop_constraint(
        "fk_action_approval_gated_app_id", "action_approval", type_="foreignkey"
    )
    op.drop_column("action_approval", "gated_app_id")
    op.create_foreign_key(
        "fk_action_approval_external_app_id",
        "action_approval",
        "external_app",
        ["external_app_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- gated_action_policy -> external_app_policy ---------------------
    op.add_column(
        "gated_action_policy",
        sa.Column("external_app_id", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE gated_action_policy p SET external_app_id = g.external_app_id "
        "FROM gated_app g WHERE g.id = p.gated_app_id"
    )
    op.drop_constraint("uq_gated_action_policy", "gated_action_policy", type_="unique")
    op.drop_constraint(
        "gated_action_policy_gated_app_id_fkey",
        "gated_action_policy",
        type_="foreignkey",
    )
    op.drop_column("gated_action_policy", "gated_app_id")
    op.execute("DELETE FROM gated_action_policy WHERE external_app_id IS NULL")
    op.alter_column("gated_action_policy", "external_app_id", nullable=False)
    op.create_foreign_key(
        "external_app_policy_external_app_id_fkey",
        "gated_action_policy",
        "external_app",
        ["external_app_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_external_app_policy_app_action",
        "gated_action_policy",
        ["external_app_id", "action_id"],
    )
    op.rename_table("gated_action_policy", "external_app_policy")

    op.drop_table("gated_app")
