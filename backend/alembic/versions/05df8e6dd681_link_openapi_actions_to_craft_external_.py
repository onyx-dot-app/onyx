"""link OpenAPI actions to Craft external apps

Revision ID: 05df8e6dd681
Revises: 1de9382bb263
Create Date: 2026-10-15 16:07:32.035147

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "05df8e6dd681"
down_revision = "1de9382bb263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool",
        sa.Column(
            "available_in_craft",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "external_app", sa.Column("openapi_tool_id", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_external_app_openapi_tool_id",
        "external_app",
        "tool",
        ["openapi_tool_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_external_app_openapi_tool_id", "external_app", ["openapi_tool_id"]
    )


def downgrade() -> None:
    op.execute("DELETE FROM external_app WHERE openapi_tool_id IS NOT NULL")
    op.drop_constraint(
        "uq_external_app_openapi_tool_id", "external_app", type_="unique"
    )
    op.drop_constraint(
        "fk_external_app_openapi_tool_id", "external_app", type_="foreignkey"
    )
    op.drop_column("external_app", "openapi_tool_id")
    op.drop_column("tool", "available_in_craft")
