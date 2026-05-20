"""External app tables

Revision ID: db87b27e93ef
Revises: 2c7f9d3a84a0
Create Date: 2026-05-12 14:07:05.057008

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "db87b27e93ef"
down_revision = "ea418a384b9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_app",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "app_type",
            sa.String(),
            nullable=False,
            server_default="CUSTOM",
        ),
        sa.Column(
            "upstream_url_patterns",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "auth_template",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "organization_credentials",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", name="uq_external_app_skill_id"),
    )

    op.create_table(
        "external_app_user_credential",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_credentials",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["external_app_id"], ["external_app.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_app_id",
            "user_id",
            name="uq_external_app_user_credential_app_user",
        ),
    )
    op.create_index(
        "ix_external_app_user_credential_user_id",
        "external_app_user_credential",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_app_user_credential_user_id",
        table_name="external_app_user_credential",
    )
    op.drop_table("external_app_user_credential")
    op.drop_table("external_app")
