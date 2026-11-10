"""Add skill versions.

Revision ID: 6476b236ec97
Revises: fdaeeca238a1
Create Date: 2026-11-07 13:01:52.644604

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6476b236ec97"
down_revision = "fdaeeca238a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("bundle_file_id", sa.String(), nullable=True),
        sa.Column("bundle_sha256", sa.String(64), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unpacked_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("frontmatter", postgresql.JSONB(), nullable=True),
        sa.Column("skill_md", sa.Text(), nullable=True),
        sa.Column(
            "metadata_unrepairable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "skill_id", "version_number", name="uq_skill_version_number"
        ),
        sa.UniqueConstraint("id", "skill_id", name="uq_skill_version_id_skill_id"),
    )
    op.add_column(
        "skill",
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_skill_current_version",
        "skill",
        "skill_version",
        ["current_version_id", "id"],
        ["id", "skill_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    # Version 1 reuses the owning skill's ID, so template clones stay deterministic.
    op.execute(
        """
        INSERT INTO skill_version (
            id, skill_id, version_number, bundle_file_id, bundle_sha256,
            is_valid, created_by_user_id, created_at
        )
        SELECT id, id, 1, bundle_file_id, bundle_sha256,
               is_valid, author_user_id, created_at
        FROM skill
        WHERE built_in_skill_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE skill SET current_version_id = id
        WHERE built_in_skill_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_skill_current_version", "skill", type_="foreignkey")
    op.drop_column("skill", "current_version_id")
    op.drop_table("skill_version")
