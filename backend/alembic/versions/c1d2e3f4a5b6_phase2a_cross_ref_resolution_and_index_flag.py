"""phase2a cross-ref resolution and index flag

Revision ID: c1d2e3f4a5b6
Revises: b3e9f2a1c8d0
Create Date: 2026-04-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b3e9f2a1c8d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kl_wiki_page",
        sa.Column(
            "is_index_page",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "kl_cross_ref",
        sa.Column(
            "to_topic_id",
            sa.Integer,
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_kl_cross_ref_to_topic_id",
        "kl_cross_ref",
        "kl_topic_ext",
        ["to_topic_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_kl_cross_ref_to_topic_id", "kl_cross_ref", type_="foreignkey")
    op.drop_column("kl_cross_ref", "to_topic_id")
    op.drop_column("kl_wiki_page", "is_index_page")
