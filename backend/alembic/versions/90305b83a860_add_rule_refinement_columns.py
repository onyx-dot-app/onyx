"""add_rule_refinement_columns

Revision ID: 90305b83a860
Revises: 61ea78857c97
Create Date: 2026-04-12 18:01:40.882150

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "90305b83a860"
down_revision = "61ea78857c97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proposal_review_rule",
        sa.Column(
            "refinement_needed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "proposal_review_rule",
        sa.Column("refinement_question", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposal_review_rule", "refinement_question")
    op.drop_column("proposal_review_rule", "refinement_needed")
