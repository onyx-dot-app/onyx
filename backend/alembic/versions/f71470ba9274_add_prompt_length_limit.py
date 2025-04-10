"""add prompt length limit

Revision ID: f71470ba9274
Revises: 6a804aeb4830
Create Date: 2025-04-01 15:07:14.977435

"""

# revision identifiers, used by Alembic.
revision = "f71470ba9274"
down_revision = "6a804aeb4830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # op.alter_column(
    #     "prompt",
    #     "system_prompt",
    #     existing_type=sa.TEXT(),
    #     type_=sa.String(length=8000),
    #     existing_nullable=False,
    # )
    # op.alter_column(
    #     "prompt",
    #     "task_prompt",
    #     existing_type=sa.TEXT(),
    #     type_=sa.String(length=8000),
    #     existing_nullable=False,
    # )
    pass


def downgrade() -> None:
    # op.alter_column(
    #     "prompt",
    #     "system_prompt",
    #     existing_type=sa.String(length=8000),
    #     type_=sa.TEXT(),
    #     existing_nullable=False,
    # )
    # op.alter_column(
    #     "prompt",
    #     "task_prompt",
    #     existing_type=sa.String(length=8000),
    #     type_=sa.TEXT(),
    #     existing_nullable=False,
    # )
    pass
