"""Re-sync the plugin tables from the skill tables after access writes.

Until access was written to the plugin tables, Onyx wrote shares, publishing,
install settings, choices and transfers only to the skill rows. This revision
runs the same re-sync as 88184258ae59 again, so the plugin rows match the
skill rows that old code changed after that revision.

Revision ID: 4ea385d01d75
Revises: 88184258ae59
Create Date: 2026-11-11 13:44:02.423627

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4ea385d01d75"
down_revision = "88184258ae59"
branch_labels = None
depends_on = None


# The rest of this file is a verbatim copy of 88184258ae59. Migrations must not
# import each other, because a later change to one would change the other.

ORGANIZATION_LIBRARY_ID = "00000000-0000-4000-8000-00000000011b"
ORGANIZATION_LIBRARY_CREATED_AT = "2026-11-11 00:00:00+00"


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
            ELSE md5('account_uploads:' || s.author_user_id::text)::uuid
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

_INSERT_ACCOUNT_UPLOADS = """
    INSERT INTO plugin_marketplace
        (id, kind, name, owner_user_id, default_installation_policy, created_at)
    SELECT
        md5('account_uploads:' || s.author_user_id::text)::uuid,
        'account_uploads',
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
        id, name, description, kind, marketplace_id, author_user_id,
        installation_policy, current_version_id, published_version_id,
        created_at, updated_at
    )
    SELECT
        id, name, description, 'skill', marketplace_id, author_user_id,
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
# in 64 characters. Only plugin.name changes: plugin_skill.name and the legacy
# skill.name keep the skill name.
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
                id, name, description, kind, marketplace_id, author_user_id,
                installation_policy, current_version_id, published_version_id,
                created_at, updated_at
            )
            VALUES (
                pending.id, candidate, pending.description, 'skill',
                pending.marketplace_id, pending.author_user_id,
                pending.installation_policy, pending.id,
                pending.published_version_id, pending.created_at,
                pending.updated_at
            );
        END LOOP;
    END
    $$
"""

# Version 1 holds the skill's current bundle. The file list, sizes, SKILL.md
# text and frontmatter stay NULL until the repair task reads the bundle.
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

_INSERT_PLUGIN_SKILLS = """
    INSERT INTO plugin_skill (id, plugin_version_id, path, name)
    SELECT s.id, s.id, '', s.name
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
        _INSERT_ACCOUNT_UPLOADS,
        _INSERT_PLUGINS_KEEPING_NAME,
        _INSERT_PLUGINS_WITH_FREE_NAME,
        _INSERT_VERSIONS,
        _INSERT_PLUGIN_SKILLS,
        _INSERT_USER_SHARES,
        _INSERT_GROUP_SHARES,
        _INSERT_PREFERENCES,
    ):
        op.execute(statement)


# --- Re-sync. Every statement is deterministic and safe to run twice. ---

_DELETE_PLUGINS_WITHOUT_SKILL = """
    DELETE FROM plugin p
    WHERE p.kind = 'skill'
      AND NOT EXISTS (
          SELECT 1 FROM skill s
          WHERE s.id = p.id AND s.built_in_skill_id IS NULL
      )
"""

# A skill whose bundle is not the bundle of its plugin's current version gets
# a new version with that bundle. Like version 1 of the backfill, it has no
# file list, SKILL.md text or frontmatter until the repair task reads it.
_CHANGED_BUNDLE_VERSION_ID = "md5(p.id::text || s.bundle_file_id)::uuid"

_CHANGED_BUNDLES = """
    FROM plugin p
    JOIN skill s ON s.id = p.id
    JOIN plugin_version current_version
        ON current_version.id = p.current_version_id
    WHERE s.built_in_skill_id IS NULL
      AND s.bundle_file_id IS NOT NULL
      AND current_version.bundle_file_id IS DISTINCT FROM s.bundle_file_id
"""

_INSERT_CHANGED_BUNDLE_VERSIONS = f"""
    INSERT INTO plugin_version (
        id, plugin_id, version_number, bundle_file_id, bundle_sha256, is_valid,
        created_by_user_id, created_by_email, created_at
    )
    SELECT
        {_CHANGED_BUNDLE_VERSION_ID},
        p.id,
        (
            SELECT max(v.version_number) FROM plugin_version v
            WHERE v.plugin_id = p.id
        ) + 1,
        s.bundle_file_id,
        s.bundle_sha256,
        s.is_valid,
        NULL,
        NULL,
        s.updated_at
    {_CHANGED_BUNDLES}
    ON CONFLICT DO NOTHING
"""

_INSERT_CHANGED_BUNDLE_SKILLS = f"""
    INSERT INTO plugin_skill (id, plugin_version_id, path, name)
    SELECT {_CHANGED_BUNDLE_VERSION_ID}, {_CHANGED_BUNDLE_VERSION_ID}, '', s.name
    {_CHANGED_BUNDLES}
    ON CONFLICT DO NOTHING
"""

_MOVE_CURRENT_TO_CHANGED_BUNDLE = f"""
    UPDATE plugin p
    SET current_version_id = {_CHANGED_BUNDLE_VERSION_ID},
        description = s.description,
        updated_at = s.updated_at
    FROM skill s, plugin_version current_version
    WHERE s.id = p.id
      AND s.built_in_skill_id IS NULL
      AND s.bundle_file_id IS NOT NULL
      AND current_version.id = p.current_version_id
      AND current_version.bundle_file_id IS DISTINCT FROM s.bundle_file_id
      AND EXISTS (
          SELECT 1 FROM plugin_version v
          WHERE v.id = {_CHANGED_BUNDLE_VERSION_ID} AND v.plugin_id = p.id
      )
"""

# The marketplace each skill's plugin belongs in, by the backfill rule.
_TARGET_MARKETPLACE = f"""
    CASE
        WHEN s.public_permission IS NOT NULL OR s.author_user_id IS NULL
            THEN '{ORGANIZATION_LIBRARY_ID}'::uuid
        ELSE md5('account_uploads:' || s.author_user_id::text)::uuid
    END
"""

# A plugin that moves to another marketplace keeps its skill name when it is
# free there, else takes the first free <name>-N, as the backfill does.
_MOVE_PLUGINS_TO_TARGET_MARKETPLACE = f"""
    DO $$
    DECLARE
        pending record;
        candidate text;
        suffix integer;
    BEGIN
        FOR pending IN
            SELECT p.id, s.name, {_TARGET_MARKETPLACE} AS marketplace_id
            FROM plugin p
            JOIN skill s ON s.id = p.id
            WHERE s.built_in_skill_id IS NULL
              AND p.marketplace_id <> {_TARGET_MARKETPLACE}
            ORDER BY s.created_at, s.id
        LOOP
            candidate := pending.name;
            suffix := 1;
            WHILE EXISTS (
                SELECT 1 FROM plugin
                WHERE marketplace_id = pending.marketplace_id
                  AND name = candidate
                  AND id <> pending.id
            ) LOOP
                suffix := suffix + 1;
                candidate := left(pending.name, 63 - length(suffix::text))
                    || '-' || suffix::text;
            END LOOP;
            UPDATE plugin
            SET marketplace_id = pending.marketplace_id, name = candidate
            WHERE id = pending.id;
        END LOOP;
    END
    $$
"""

# Published means: in the Organization library. Phase 1 runs the newest
# version there, so the published pointer is the current one.
_SYNC_OWNER_POLICY_AND_PUBLISHED = f"""
    UPDATE plugin p
    SET author_user_id = s.author_user_id,
        installation_policy = NULLIF(s.installation_policy, 'AVAILABLE'),
        published_version_id = CASE
            WHEN p.marketplace_id = '{ORGANIZATION_LIBRARY_ID}'::uuid
                THEN p.current_version_id
        END
    FROM skill s
    WHERE s.id = p.id
      AND s.built_in_skill_id IS NULL
      AND (
          p.author_user_id IS DISTINCT FROM s.author_user_id
          OR p.installation_policy
              IS DISTINCT FROM NULLIF(s.installation_policy, 'AVAILABLE')
          OR p.published_version_id IS DISTINCT FROM CASE
              WHEN p.marketplace_id = '{ORGANIZATION_LIBRARY_ID}'::uuid
                  THEN p.current_version_id
          END
      )
"""

# The backfill inserts missing shares and choices. These remove the ones the
# skill no longer has and copy changed levels.
_DELETE_STALE_USER_SHARES = """
    DELETE FROM plugin__user pu
    USING skill s
    WHERE s.id = pu.plugin_id
      AND s.built_in_skill_id IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM skill__user su
          WHERE su.skill_id = pu.plugin_id AND su.user_id = pu.user_id
      )
"""

_UPDATE_USER_SHARES = """
    UPDATE plugin__user pu
    SET permission = su.permission
    FROM skill__user su
    WHERE su.skill_id = pu.plugin_id
      AND su.user_id = pu.user_id
      AND pu.permission <> su.permission
"""

_DELETE_STALE_GROUP_SHARES = """
    DELETE FROM plugin__user_group pg
    USING skill s
    WHERE s.id = pg.plugin_id
      AND s.built_in_skill_id IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM skill__user_group sg
          WHERE sg.skill_id = pg.plugin_id
            AND sg.user_group_id = pg.user_group_id
      )
"""

_UPDATE_GROUP_SHARES = """
    UPDATE plugin__user_group pg
    SET permission = sg.permission
    FROM skill__user_group sg
    WHERE sg.skill_id = pg.plugin_id
      AND sg.user_group_id = pg.user_group_id
      AND pg.permission IS DISTINCT FROM sg.permission
"""

_DELETE_STALE_PREFERENCES = """
    DELETE FROM user_plugin_preference upp
    USING skill s
    WHERE s.id = upp.plugin_id
      AND s.built_in_skill_id IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM user_skill_preference usp
          WHERE usp.skill_id = upp.plugin_id AND usp.user_id = upp.user_id
      )
"""

_UPDATE_PREFERENCES = """
    UPDATE user_plugin_preference upp
    SET enabled = usp.enabled
    FROM user_skill_preference usp
    WHERE usp.skill_id = upp.plugin_id
      AND usp.user_id = upp.user_id
      AND upp.enabled <> usp.enabled
"""


def resync_plugins_from_skills() -> None:
    """Make the plugin rows of custom skills match the skill rows. Ids come
    from skill ids, bundle file ids or fixed literals."""
    op.execute(_DELETE_PLUGINS_WITHOUT_SKILL)
    backfill_plugins_from_skills()
    for statement in (
        _INSERT_CHANGED_BUNDLE_VERSIONS,
        _INSERT_CHANGED_BUNDLE_SKILLS,
        _MOVE_CURRENT_TO_CHANGED_BUNDLE,
        _MOVE_PLUGINS_TO_TARGET_MARKETPLACE,
        _SYNC_OWNER_POLICY_AND_PUBLISHED,
        _DELETE_STALE_USER_SHARES,
        _UPDATE_USER_SHARES,
        _DELETE_STALE_GROUP_SHARES,
        _UPDATE_GROUP_SHARES,
        _DELETE_STALE_PREFERENCES,
        _UPDATE_PREFERENCES,
    ):
        op.execute(statement)


def upgrade() -> None:
    resync_plugins_from_skills()


def downgrade() -> None:
    # A data sync. The plugin rows stay as they are.
    pass
