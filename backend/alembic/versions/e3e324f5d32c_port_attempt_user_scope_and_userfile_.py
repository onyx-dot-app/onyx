"""port_attempt_user_scope_and_userfile_secondary_pending

Revision ID: e3e324f5d32c
Revises: 9d2e7f1a4c58
Create Date: 2026-07-08 13:23:34.712903

Reindexing user-file port, phase 1 (additive, dark until a port-flow reindex runs):
make PortAttempt / PortOrphanCandidate scope-polymorphic (connector cc_pair OR user)
and add UserFile.secondary_only_sync_pending (the deferred FUTURE sync flag) + the
enumeration/cursor indexes the port scheduler needs.

Indexes are built non-concurrently (repo convention; migrations run per-schema inside
a transaction). The added tables are small; user_file gets three indexes — its column
add is metadata-only, but the index builds briefly lock writes on a large table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e3e324f5d32c"
down_revision = "9d2e7f1a4c58"
branch_labels = None
depends_on = None

_ACTIVE_PREDICATE = "status IN ('NOT_STARTED', 'IN_PROGRESS')"


def upgrade() -> None:
    # port_attempt
    op.alter_column(
        "port_attempt", "cc_pair_id", existing_type=sa.Integer(), nullable=True
    )
    op.add_column(
        "port_attempt",
        sa.Column("port_user_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "port_attempt_port_user_id_fkey",
        "port_attempt",
        "user",
        ["port_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_port_attempt_port_user_id"), "port_attempt", ["port_user_id"]
    )
    op.create_check_constraint(
        "ck_port_attempt_exactly_one_scope",
        "port_attempt",
        "num_nonnulls(cc_pair_id, port_user_id) = 1",
    )
    # rescope the connector index to cc_pair rows (predicates can't be altered in place)
    op.drop_index("ix_port_attempt_active_unique", table_name="port_attempt")
    op.create_index(
        "ix_port_attempt_active_unique",
        "port_attempt",
        ["cc_pair_id", "search_settings_id"],
        unique=True,
        postgresql_where=sa.text(f"{_ACTIVE_PREDICATE} AND cc_pair_id IS NOT NULL"),
    )
    op.create_index(
        "ix_port_attempt_active_unique_user",
        "port_attempt",
        ["port_user_id", "search_settings_id"],
        unique=True,
        postgresql_where=sa.text(f"{_ACTIVE_PREDICATE} AND port_user_id IS NOT NULL"),
    )

    # port_orphan_candidate
    op.alter_column(
        "port_orphan_candidate", "cc_pair_id", existing_type=sa.Integer(), nullable=True
    )
    op.add_column(
        "port_orphan_candidate",
        sa.Column("port_user_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "port_orphan_candidate_port_user_id_fkey",
        "port_orphan_candidate",
        "user",
        ["port_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_port_orphan_candidate_port_user_id"),
        "port_orphan_candidate",
        ["port_user_id"],
    )
    op.create_check_constraint(
        "ck_port_orphan_candidate_exactly_one_scope",
        "port_orphan_candidate",
        "num_nonnulls(cc_pair_id, port_user_id) = 1",
    )
    # per-scope partial-unique indexes (NULLs are distinct in PG, so one all-column
    # key can't dedup user rows)
    op.drop_constraint(
        "uq_port_orphan_candidate_settings_ccpair_doc",
        "port_orphan_candidate",
        type_="unique",
    )
    op.create_index(
        "uq_port_orphan_candidate_connector",
        "port_orphan_candidate",
        ["search_settings_id", "cc_pair_id", "document_id"],
        unique=True,
        postgresql_where=sa.text("cc_pair_id IS NOT NULL"),
    )
    op.create_index(
        "uq_port_orphan_candidate_user",
        "port_orphan_candidate",
        ["search_settings_id", "port_user_id", "document_id"],
        unique=True,
        postgresql_where=sa.text("port_user_id IS NOT NULL"),
    )

    # user_file
    op.add_column(
        "user_file",
        sa.Column(
            "secondary_only_sync_pending",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_file_secondary_only_sync_pending",
        "user_file",
        ["id"],
        postgresql_where=sa.text("secondary_only_sync_pending IS TRUE"),
    )
    op.create_index(
        "ix_user_file_user_status_id",
        "user_file",
        ["user_id", "status", "id"],
    )
    op.create_index(
        "ix_user_file_user_id_completed",
        "user_file",
        ["user_id"],
        postgresql_where=sa.text("status = 'COMPLETED'"),
    )


def downgrade() -> None:
    # user_file
    op.drop_index("ix_user_file_user_id_completed", table_name="user_file")
    op.drop_index("ix_user_file_user_status_id", table_name="user_file")
    op.drop_index("ix_user_file_secondary_only_sync_pending", table_name="user_file")
    op.drop_column("user_file", "secondary_only_sync_pending")

    # port_orphan_candidate
    # user-scope rows have cc_pair_id NULL and can't exist in the connector-only
    # schema; drop them before restoring NOT NULL.
    op.execute("DELETE FROM port_orphan_candidate WHERE port_user_id IS NOT NULL")
    op.drop_index("uq_port_orphan_candidate_user", table_name="port_orphan_candidate")
    op.drop_index(
        "uq_port_orphan_candidate_connector", table_name="port_orphan_candidate"
    )
    op.create_unique_constraint(
        "uq_port_orphan_candidate_settings_ccpair_doc",
        "port_orphan_candidate",
        ["search_settings_id", "cc_pair_id", "document_id"],
    )
    op.drop_constraint(
        "ck_port_orphan_candidate_exactly_one_scope",
        "port_orphan_candidate",
        type_="check",
    )
    op.drop_index(
        op.f("ix_port_orphan_candidate_port_user_id"),
        table_name="port_orphan_candidate",
    )
    op.drop_constraint(
        "port_orphan_candidate_port_user_id_fkey",
        "port_orphan_candidate",
        type_="foreignkey",
    )
    op.drop_column("port_orphan_candidate", "port_user_id")
    op.alter_column(
        "port_orphan_candidate",
        "cc_pair_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # port_attempt
    op.execute("DELETE FROM port_attempt WHERE port_user_id IS NOT NULL")
    op.drop_index("ix_port_attempt_active_unique_user", table_name="port_attempt")
    op.drop_index("ix_port_attempt_active_unique", table_name="port_attempt")
    op.create_index(
        "ix_port_attempt_active_unique",
        "port_attempt",
        ["cc_pair_id", "search_settings_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_PREDICATE),
    )
    op.drop_constraint(
        "ck_port_attempt_exactly_one_scope", "port_attempt", type_="check"
    )
    op.drop_index(op.f("ix_port_attempt_port_user_id"), table_name="port_attempt")
    op.drop_constraint(
        "port_attempt_port_user_id_fkey", "port_attempt", type_="foreignkey"
    )
    op.drop_column("port_attempt", "port_user_id")
    op.alter_column(
        "port_attempt", "cc_pair_id", existing_type=sa.Integer(), nullable=False
    )
