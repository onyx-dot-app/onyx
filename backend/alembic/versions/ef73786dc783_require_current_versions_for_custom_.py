"""Require current versions for custom skills.

Revision ID: ef73786dc783
Revises: 8fc170c91f59
Create Date: 2026-11-08 06:29:00.235027

V7 ships in the next planned release. Drain pre-V7 writers before upgrade.
Retain physical legacy columns for V8, at least one release after V7.
"""

from alembic import op

revision = "ef73786dc783"
down_revision = "8fc170c91f59"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Serialize reconciliation before fencing legacy writers.
    op.execute("LOCK TABLE skill, skill_version IN ACCESS EXCLUSIVE MODE")
    op.execute("SET CONSTRAINTS fk_skill_current_version IMMEDIATE")
    # Preserve history, including missing/pruned bundles. Copy only known references.
    # UUIDs and timestamps depend solely on existing rows, so clones stay identical.
    op.execute("""
        WITH recovery AS (
            SELECT s.*, COALESCE((SELECT max(v.version_number) FROM skill_version v
                                  WHERE v.skill_id = s.id), 0) + 1 AS number
            FROM skill s LEFT JOIN skill_version v ON v.id = s.current_version_id
            WHERE s.built_in_skill_id IS NULL AND (
                v.id IS NULL OR v.bundle_file_id IS DISTINCT FROM s.bundle_file_id
                OR v.bundle_sha256 IS DISTINCT FROM s.bundle_sha256)
        ), inserted AS (
            INSERT INTO skill_version (
                id, skill_id, version_number, bundle_file_id, bundle_sha256,
                is_valid, created_at
            )
            SELECT md5(id::text || ':v7:' || number::text)::uuid, id, number,
                   bundle_file_id, bundle_sha256, is_valid, updated_at
            FROM recovery
            RETURNING id, skill_id
        )
        UPDATE skill s SET current_version_id = i.id
        FROM inserted i WHERE s.id = i.skill_id
    """)
    op.execute("""
        UPDATE skill_version v SET is_valid = s.is_valid
        FROM skill s WHERE v.id = s.current_version_id
        AND s.built_in_skill_id IS NULL
        AND v.is_valid IS DISTINCT FROM s.is_valid
    """)
    op.drop_constraint("ck_skill_definition_source", "skill", type_="check")
    op.execute("""
        UPDATE skill SET current_version_id = NULL
        WHERE built_in_skill_id IS NOT NULL
    """)
    op.create_check_constraint(
        "ck_skill_definition_source",
        "skill",
        "(built_in_skill_id IS NULL) <> (current_version_id IS NULL)",
    )
    op.execute("""
        UPDATE skill SET bundle_file_id = NULL, bundle_sha256 = NULL, is_valid = NULL
    """)
    op.create_check_constraint(
        "ck_skill_legacy_fields_retired",
        "skill",
        "bundle_file_id IS NULL AND bundle_sha256 IS NULL AND is_valid IS NULL",
    )
    op.execute("SET CONSTRAINTS fk_skill_current_version DEFERRED")


def downgrade() -> None:
    op.execute("LOCK TABLE skill, skill_version IN ACCESS EXCLUSIVE MODE")
    op.execute("SET CONSTRAINTS fk_skill_current_version IMMEDIATE")
    # The old check cannot represent missing bundle links. Do not invent one.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM skill s LEFT JOIN skill_version v
                ON v.id = s.current_version_id
                WHERE s.built_in_skill_id IS NULL AND v.bundle_file_id IS NULL
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade skills without current bundle references; replace their content or delete them first';
            END IF;
        END $$
    """)
    op.drop_constraint("ck_skill_legacy_fields_retired", "skill", type_="check")
    op.execute("""
        UPDATE skill s SET bundle_file_id = v.bundle_file_id,
            bundle_sha256 = v.bundle_sha256, is_valid = v.is_valid
        FROM skill_version v WHERE s.current_version_id = v.id
        AND s.built_in_skill_id IS NULL
    """)
    op.execute("""
        UPDATE skill SET bundle_file_id = NULL, bundle_sha256 = NULL, is_valid = NULL
        WHERE built_in_skill_id IS NOT NULL
    """)
    op.drop_constraint("ck_skill_definition_source", "skill", type_="check")
    op.create_check_constraint(
        "ck_skill_definition_source",
        "skill",
        "(built_in_skill_id IS NULL) <> (bundle_file_id IS NULL)",
    )
    op.execute("SET CONSTRAINTS fk_skill_current_version DEFERRED")
