"""Add flow_node_run.iteration for steps inside a loop

Revision ID: 1c8625164cc5
Revises: b03621dce5db
Create Date: 2026-06-03 21:36:08.114527

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "1c8625164cc5"
down_revision = "b03621dce5db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A step inside a loop runs once per pass, so (run, node, item) no longer
    # names one execution. Existing rows are all outside any loop: pass 0.
    op.add_column(
        "flow_node_run",
        sa.Column(
            "iteration", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.drop_constraint("uq_flow_node_run_identity", "flow_node_run", type_="unique")
    op.create_unique_constraint(
        "uq_flow_node_run_identity",
        "flow_node_run",
        ["run_id", "node_id", "iteration", "item_index"],
    )


def downgrade() -> None:
    # Later passes have no key of their own without the column. They are
    # history, not state a run needs, so they go rather than block the
    # downgrade on the old constraint.
    op.execute("DELETE FROM flow_node_run WHERE iteration > 0")
    op.drop_constraint("uq_flow_node_run_identity", "flow_node_run", type_="unique")
    op.create_unique_constraint(
        "uq_flow_node_run_identity",
        "flow_node_run",
        ["run_id", "node_id", "item_index"],
    )
    op.drop_column("flow_node_run", "iteration")
