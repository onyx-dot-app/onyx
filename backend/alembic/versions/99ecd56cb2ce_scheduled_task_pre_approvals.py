"""scheduled task pre-approvals

Per-app pre-approval grants on scheduled tasks: the egress gate skips
the approval park for a RUNNING scheduled run whose task grants the
matched app. ``decided_via`` distinguishes pre-approved audit rows from
human clicks; ``external_app_id`` makes the run-history feedback loop
resolvable (``app_name`` is not unique across app instances).

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
    op.add_column(
        "scheduled_task",
        sa.Column(
            "pre_approved_app_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
    op.drop_column("scheduled_task", "pre_approved_app_ids")
