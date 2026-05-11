"""skills

Revision ID: 7632ddcfd011
Revises: 4ff2545411ad
Create Date: 2026-05-11 15:28:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7632ddcfd011"
down_revision = "4ff2545411ad"
branch_labels = None
depends_on = None


def _add_skill_bundle_to_legacy_fileorigin_enum() -> None:
    """Expand old native Postgres fileorigin enums if a deployment still has one.

    FileOrigin is string-backed in the modern schema, so most deployments will not have
    a native ``fileorigin`` type. When one does exist, keep the lookup scoped to the
    schema currently being migrated and run the enum DDL in Alembic's autocommit block.
    """

    migration_context = op.get_context()
    if migration_context.as_sql:
        op.execute(
            "-- Skipping legacy fileorigin enum expansion in offline mode; "
            "online migration checks the active schema."
        )
        return

    bind = op.get_bind()
    enum_schema = bind.execute(sa.text("""
            SELECT n.nspname
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typname = 'fileorigin'
              AND n.nspname = current_schema()
        """)).scalar_one_or_none()
    if enum_schema is None:
        return

    quoted_schema = bind.dialect.identifier_preparer.quote_schema(enum_schema)
    with migration_context.autocommit_block():
        op.execute(
            f"ALTER TYPE {quoted_schema}.fileorigin "
            "ADD VALUE IF NOT EXISTS 'skill_bundle'"
        )


def upgrade() -> None:
    _add_skill_bundle_to_legacy_fileorigin_enum()

    op.create_table(
        "skill",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("bundle_file_id", sa.String(), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "manifest_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_skill_slug", "skill", ["slug"], unique=True)

    op.create_table(
        "skill__user_group",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skill.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"],
            ["user_group.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("skill_id", "user_group_id"),
    )


def downgrade() -> None:
    op.drop_table("skill__user_group")
    op.drop_index("ux_skill_slug", table_name="skill")
    op.drop_table("skill")
    # PostgreSQL enum values cannot be removed with a simple ALTER TYPE. This
    # migration only appends to legacy native enums when they still exist, and the
    # modern schema stores FileOrigin as a string-backed enum.
