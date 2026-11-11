"""Add the plugin tables and backfill one plugin for each custom skill.

Revision ID: cdec9dd9ca3d
Revises: fdaeeca238a1
Create Date: 2026-11-11 12:43:58.598815

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "cdec9dd9ca3d"
down_revision = "fdaeeca238a1"
branch_labels = None
depends_on = None


ORGANIZATION_LIBRARY_ID = "00000000-0000-4000-8000-00000000011b"
ORGANIZATION_LIBRARY_CREATED_AT = "2026-11-11 00:00:00+00"

_INSTALLATION_POLICIES = ("REQUIRED", "DEFAULT", "AVAILABLE", "NOT_AVAILABLE")
_SHARE_PERMISSIONS = ("EDITOR", "VIEWER")


def _installation_policy_type() -> sa.Enum:
    return sa.Enum(*_INSTALLATION_POLICIES, native_enum=False)


def _share_permission_type() -> sa.Enum:
    return sa.Enum(*_SHARE_PERMISSIONS, native_enum=False)


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _create_tables() -> None:
    op.create_table(
        "plugin_marketplace",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kind",
            sa.Enum("user_uploads", "organization_library", native_enum=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "default_installation_policy",
            _installation_policy_type(),
            server_default="AVAILABLE",
            nullable=False,
        ),
        _created_at_column(),
        sa.CheckConstraint(
            "(kind = 'user_uploads') = (owner_user_id IS NOT NULL)",
            name="ck_plugin_marketplace_owner_iff_user_uploads",
        ),
    )
    op.create_index(
        "uq_plugin_marketplace_organization_library",
        "plugin_marketplace",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'organization_library'"),
    )
    op.create_index(
        "uq_plugin_marketplace_user_uploads_owner",
        "plugin_marketplace",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'user_uploads'"),
    )

    op.create_table(
        "plugin",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "marketplace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin_marketplace.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("installation_policy", _installation_policy_type(), nullable=True),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        _created_at_column(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "marketplace_id", "name", name="uq_plugin_marketplace_name"
        ),
        sa.CheckConstraint(
            "published_version_id IS NOT NULL OR author_user_id IS NOT NULL",
            name="ck_private_plugin_has_owner",
        ),
    )
    op.create_index("ix_plugin_author_user_id", "plugin", ["author_user_id"])

    op.create_table(
        "plugin_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("bundle_file_id", sa.String(), nullable=True),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True),
        sa.Column("file_manifest", postgresql.JSONB(), nullable=True),
        sa.Column("unpacked_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_email", sa.String(), nullable=True),
        _created_at_column(),
        sa.UniqueConstraint(
            "plugin_id", "version_number", name="uq_plugin_version_plugin_number"
        ),
        sa.UniqueConstraint("id", "plugin_id", name="uq_plugin_version_id_plugin"),
    )

    # A pointer must name a version of the same plugin. Deferred, so one
    # transaction inserts a plugin and its first version.
    for name, column in (
        ("fk_plugin_current_version", "current_version_id"),
        ("fk_plugin_published_version", "published_version_id"),
    ):
        op.create_foreign_key(
            name,
            "plugin",
            "plugin_version",
            [column, "id"],
            ["id", "plugin_id"],
            deferrable=True,
            initially="DEFERRED",
        )

    op.create_table(
        "plugin_skill",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plugin_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(), server_default="", nullable=False),
        sa.Column("skill_md", sa.Text(), nullable=True),
        sa.Column("frontmatter", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "coalesce(jsonb_typeof(frontmatter -> 'name'), '') = 'string'",
            name="ck_plugin_skill_frontmatter_name",
        ),
    )
    op.create_index(
        "uq_plugin_skill_version_name",
        "plugin_skill",
        ["plugin_version_id", sa.text("(frontmatter ->> 'name')")],
        unique=True,
    )

    op.create_table(
        "plugin__user",
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission",
            _share_permission_type(),
            server_default="VIEWER",
            nullable=False,
        ),
        _created_at_column(),
    )
    op.create_index("ix_plugin__user_user_id", "plugin__user", ["user_id"])

    op.create_table(
        "plugin__user_group",
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_group_id",
            sa.Integer(),
            sa.ForeignKey("user_group.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", _share_permission_type(), nullable=True),
        sa.Column("installation_policy", _installation_policy_type(), nullable=True),
        _created_at_column(),
    )
    op.create_index(
        "ix_plugin__user_group_user_group_id",
        "plugin__user_group",
        ["user_group_id"],
    )

    op.create_table(
        "user_plugin_preference",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "plugin_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plugin.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_user_plugin_preference_plugin_id",
        "user_plugin_preference",
        ["plugin_id"],
    )


# The backfill below is a frozen copy of the sync rules, so later re-sync
# migrations can copy it verbatim. Each statement skips rows that exist, so a
# second run adds only skills that have no plugin yet. It never updates rows.

# Each custom skill with no plugin, with the plugin values it maps to. Public
# and author-less skills go to the Organization library, published at
# version 1 (version id = skill id). Others go to the author's "My uploads".
# AVAILABLE maps to NULL, so the plugin follows its marketplace default.
_UNSYNCED_CUSTOM_SKILLS = f"""
    SELECT
        s.id,
        s.name,
        s.description,
        s.author_user_id,
        s.created_at,
        s.updated_at,
        CASE
            WHEN s.public_permission IS NOT NULL OR s.author_user_id IS NULL
                THEN '{ORGANIZATION_LIBRARY_ID}'::uuid
            ELSE md5('user_uploads:' || s.author_user_id::text)::uuid
        END AS marketplace_id,
        NULLIF(s.installation_policy, 'AVAILABLE') AS installation_policy,
        CASE
            WHEN s.public_permission IS NOT NULL OR s.author_user_id IS NULL
                THEN s.id
        END AS published_version_id
    FROM skill s
    WHERE s.built_in_skill_id IS NULL
      AND NOT EXISTS (SELECT 1 FROM plugin p WHERE p.id = s.id)
"""

_INSERT_ORGANIZATION_LIBRARY = f"""
    INSERT INTO plugin_marketplace
        (id, kind, name, owner_user_id, default_installation_policy, created_at)
    VALUES (
        '{ORGANIZATION_LIBRARY_ID}',
        'organization_library',
        'Organization library',
        NULL,
        'AVAILABLE',
        TIMESTAMPTZ '{ORGANIZATION_LIBRARY_CREATED_AT}'
    )
    ON CONFLICT DO NOTHING
"""

_INSERT_USER_UPLOADS = """
    INSERT INTO plugin_marketplace
        (id, kind, name, owner_user_id, default_installation_policy, created_at)
    SELECT
        md5('user_uploads:' || s.author_user_id::text)::uuid,
        'user_uploads',
        'My uploads',
        s.author_user_id,
        'AVAILABLE',
        min(s.created_at)
    FROM skill s
    WHERE s.built_in_skill_id IS NULL AND s.author_user_id IS NOT NULL
    GROUP BY s.author_user_id
    ON CONFLICT DO NOTHING
"""

# The oldest skill (created_at, then id) of each name in a marketplace keeps
# the name, unless a plugin there has it already.
_INSERT_PLUGINS_KEEPING_NAME = f"""
    INSERT INTO plugin (
        id, name, description, marketplace_id, author_user_id,
        installation_policy, current_version_id, published_version_id,
        created_at, updated_at
    )
    SELECT
        id, name, description, marketplace_id, author_user_id,
        installation_policy, id, published_version_id, created_at, updated_at
    FROM (
        SELECT
            pending.*,
            row_number() OVER (
                PARTITION BY marketplace_id, name ORDER BY created_at, id
            ) AS name_rank
        FROM ({_UNSYNCED_CUSTOM_SKILLS}) pending
    ) ranked
    WHERE name_rank = 1
    ON CONFLICT DO NOTHING
"""

# Each other skill takes the first free name <name>-2, <name>-3, ... in its
# marketplace, counting every plugin there. The base is cut so the name fits
# in 64 characters. Only plugin.name changes: the plugin_skill frontmatter and
# the legacy skill.name keep the skill name.
_INSERT_PLUGINS_WITH_FREE_NAME = f"""
    DO $$
    DECLARE
        pending record;
        candidate text;
        suffix integer;
    BEGIN
        FOR pending IN
            {_UNSYNCED_CUSTOM_SKILLS}
            ORDER BY s.created_at, s.id
        LOOP
            candidate := pending.name;
            suffix := 1;
            WHILE EXISTS (
                SELECT 1 FROM plugin
                WHERE marketplace_id = pending.marketplace_id
                  AND name = candidate
            ) LOOP
                suffix := suffix + 1;
                candidate := left(pending.name, 63 - length(suffix::text))
                    || '-' || suffix::text;
            END LOOP;
            INSERT INTO plugin (
                id, name, description, marketplace_id, author_user_id,
                installation_policy, current_version_id, published_version_id,
                created_at, updated_at
            )
            VALUES (
                pending.id, candidate, pending.description,
                pending.marketplace_id, pending.author_user_id,
                pending.installation_policy, pending.id,
                pending.published_version_id, pending.created_at,
                pending.updated_at
            );
        END LOOP;
    END
    $$
"""

# Version 1 holds the skill's current bundle. The file list, sizes and SKILL.md
# text stay NULL until the repair task reads the bundle.
_INSERT_VERSIONS = """
    INSERT INTO plugin_version (
        id, plugin_id, version_number, bundle_file_id, bundle_sha256, is_valid,
        created_by_user_id, created_by_email, created_at
    )
    SELECT
        s.id, s.id, 1, s.bundle_file_id, s.bundle_sha256, s.is_valid,
        s.author_user_id, u.email, s.updated_at
    FROM skill s
    JOIN plugin p ON p.id = s.id
    LEFT JOIN "user" u ON u.id = s.author_user_id
    WHERE s.built_in_skill_id IS NULL
    ON CONFLICT DO NOTHING
"""

# The frontmatter starts with the name and description of the legacy row. The
# repair task replaces it with the parsed SKILL.md.
_INSERT_PLUGIN_SKILLS = """
    INSERT INTO plugin_skill (id, plugin_version_id, path, frontmatter)
    SELECT
        s.id, s.id, '',
        jsonb_build_object('name', s.name, 'description', s.description)
    FROM skill s
    JOIN plugin_version v ON v.id = s.id
    WHERE s.built_in_skill_id IS NULL
    ON CONFLICT DO NOTHING
"""

_INSERT_USER_SHARES = """
    INSERT INTO plugin__user (plugin_id, user_id, permission, created_at)
    SELECT su.skill_id, su.user_id, su.permission, s.created_at
    FROM skill__user su
    JOIN skill s ON s.id = su.skill_id
    JOIN plugin p ON p.id = su.skill_id
    WHERE s.built_in_skill_id IS NULL
    ON CONFLICT DO NOTHING
"""

_INSERT_GROUP_SHARES = """
    INSERT INTO plugin__user_group
        (plugin_id, user_group_id, permission, installation_policy, created_at)
    SELECT sg.skill_id, sg.user_group_id, sg.permission, NULL, s.created_at
    FROM skill__user_group sg
    JOIN skill s ON s.id = sg.skill_id
    JOIN plugin p ON p.id = sg.skill_id
    WHERE s.built_in_skill_id IS NULL
    ON CONFLICT DO NOTHING
"""

_INSERT_PREFERENCES = """
    INSERT INTO user_plugin_preference (user_id, plugin_id, enabled, enabled_at)
    SELECT usp.user_id, usp.skill_id, usp.enabled, NULL
    FROM user_skill_preference usp
    JOIN skill s ON s.id = usp.skill_id
    JOIN plugin p ON p.id = usp.skill_id
    WHERE s.built_in_skill_id IS NULL
    ON CONFLICT DO NOTHING
"""


def backfill_plugins_from_skills() -> None:
    """Add a plugin, version 1 and plugin_skill row for each custom skill that
    has none, then copy its shares and preferences. Built-in skills get nothing.
    Deterministic: ids come from skill ids or fixed literals."""
    for statement in (
        _INSERT_ORGANIZATION_LIBRARY,
        _INSERT_USER_UPLOADS,
        _INSERT_PLUGINS_KEEPING_NAME,
        _INSERT_PLUGINS_WITH_FREE_NAME,
        _INSERT_VERSIONS,
        _INSERT_PLUGIN_SKILLS,
        _INSERT_USER_SHARES,
        _INSERT_GROUP_SHARES,
        _INSERT_PREFERENCES,
    ):
        op.execute(statement)


def upgrade() -> None:
    _create_tables()
    backfill_plugins_from_skills()


def downgrade() -> None:
    op.drop_constraint("fk_plugin_published_version", "plugin", type_="foreignkey")
    op.drop_constraint("fk_plugin_current_version", "plugin", type_="foreignkey")
    for table in (
        "user_plugin_preference",
        "plugin__user_group",
        "plugin__user",
        "plugin_skill",
        "plugin_version",
        "plugin",
        "plugin_marketplace",
    ):
        op.drop_table(table)
