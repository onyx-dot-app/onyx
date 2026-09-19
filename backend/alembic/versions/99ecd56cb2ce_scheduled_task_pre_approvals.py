"""scheduled task pre-approvals

Per-app pre-approval grants on scheduled tasks: the egress gate skips
the approval park for a RUNNING scheduled run whose task grants the
matched app. Grants live in ``scheduled_task_pre_approved_app`` (one row
per (task, app), FK to both). ``decided_via`` distinguishes pre-approved
audit rows from human clicks; ``external_app_id`` makes the run-history
feedback loop resolvable (``app_name`` is not unique across app instances).

Revision ID: 99ecd56cb2ce
Revises: b8a5e7068be5
Create Date: 2026-06-02 17:17:53.925335

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "99ecd56cb2ce"
down_revision = "b8a5e7068be5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_task_pre_approved_app",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scheduled_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_app_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_task_id"], ["scheduled_task.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["external_app_id"], ["external_app.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scheduled_task_id",
            "external_app_id",
            name="uq_scheduled_task_pre_approved_app",
        ),
    )
    op.add_column(
        "action_approval",
        sa.Column("decided_via", sa.String(), nullable=True),
    )
    op.add_column(
        "action_approval",
        sa.Column("external_app_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_action_approval_external_app_id",
        "action_approval",
        "external_app",
        ["external_app_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_action_approval_external_app_id", "action_approval", type_="foreignkey"
    )
    op.drop_column("action_approval", "external_app_id")
    op.drop_column("action_approval", "decided_via")
    op.drop_table("scheduled_task_pre_approved_app")
