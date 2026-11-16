"""Compare the access state of custom skills with their plugins.

Until the legacy skill tables are dropped, every access write goes to both.
Tests call ``plugin_access_mismatches`` after a write to check that the two
models agree."""

import hashlib
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")

# (user id or group id, permission or enabled flag)
AccessRow = tuple[UUID | int, str | bool]


def user_uploads_id(user_id: UUID | str) -> UUID:
    return UUID(hashlib.md5(f"user_uploads:{user_id}".encode()).hexdigest())


def _rows(db_session: Session, sql: str, ids: list[UUID]) -> dict[UUID, set[AccessRow]]:
    result: dict[UUID, set[AccessRow]] = {skill_id: set() for skill_id in ids}
    for skill_id, target_id, value in db_session.execute(text(sql), {"ids": ids}):
        result[skill_id].add((target_id, value))
    return result


def plugin_access_mismatches(
    db_session: Session, skill_ids: Iterable[UUID | str]
) -> list[str]:
    """Each difference between a custom skill's legacy access rows and its
    plugin rows, as text. Empty when they match."""
    ids = [UUID(str(skill_id)) for skill_id in skill_ids]
    problems: list[str] = []
    skills = {
        row.id: row
        for row in db_session.execute(
            text(
                "SELECT id, author_user_id, public_permission, installation_policy "
                "FROM skill WHERE id = ANY(:ids) AND built_in_skill_id IS NULL"
            ),
            {"ids": ids},
        )
    }
    plugins = {
        row.id: row
        for row in db_session.execute(
            text(
                "SELECT id, author_user_id, installation_policy, marketplace_id, "
                "current_version_id, published_version_id "
                "FROM plugin WHERE id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    }
    for skill_id in ids:
        skill = skills.get(skill_id)
        plugin = plugins.get(skill_id)
        if skill is None:
            if plugin is not None:
                problems.append(f"{skill_id}: plugin has no skill")
            continue
        if plugin is None:
            problems.append(f"{skill_id}: skill has no plugin")
            continue
        if plugin.author_user_id != skill.author_user_id:
            problems.append(f"{skill_id}: author differs")
        # The legacy column has no NOT_AVAILABLE and no "no own setting"; it
        # holds AVAILABLE for an explicit AVAILABLE, NOT_AVAILABLE or none.
        expected_policy = (
            None
            if skill.installation_policy == "AVAILABLE"
            else skill.installation_policy
        )
        if plugin.installation_policy not in (
            (expected_policy, "AVAILABLE", "NOT_AVAILABLE")
            if expected_policy is None
            else (expected_policy,)
        ):
            problems.append(
                f"{skill_id}: install setting {plugin.installation_policy} "
                f"!= {expected_policy}"
            )
        if skill.public_permission is not None:
            if plugin.marketplace_id != ORGANIZATION_LIBRARY_ID:
                problems.append(f"{skill_id}: public skill is not published")
            if plugin.published_version_id is None:
                problems.append(f"{skill_id}: public skill has no published version")
        else:
            if plugin.marketplace_id != user_uploads_id(skill.author_user_id):
                problems.append(f"{skill_id}: private skill is not in My uploads")
            if plugin.published_version_id is not None:
                problems.append(f"{skill_id}: private skill has a published version")

    pairs = [
        (
            "user shares",
            "SELECT skill_id, user_id, permission FROM skill__user "
            "WHERE skill_id = ANY(:ids)",
            "SELECT plugin_id, user_id, permission FROM plugin__user "
            "WHERE plugin_id = ANY(:ids)",
        ),
        (
            "group shares",
            "SELECT skill_id, user_group_id, permission FROM skill__user_group "
            "WHERE skill_id = ANY(:ids)",
            # A row with no permission holds only a group install setting.
            "SELECT plugin_id, user_group_id, permission FROM plugin__user_group "
            "WHERE plugin_id = ANY(:ids) AND permission IS NOT NULL",
        ),
        (
            "choices",
            "SELECT skill_id, user_id, enabled FROM user_skill_preference "
            "WHERE skill_id = ANY(:ids)",
            "SELECT plugin_id, user_id, enabled FROM user_plugin_preference "
            "WHERE plugin_id = ANY(:ids)",
        ),
    ]
    custom_ids = [skill_id for skill_id in ids if skill_id in skills]
    for label, legacy_sql, plugin_sql in pairs:
        legacy = _rows(db_session, legacy_sql, custom_ids)
        plugin_rows = _rows(db_session, plugin_sql, custom_ids)
        problems.extend(
            f"{skill_id}: {label} {sorted(map(str, plugin_rows[skill_id]))} "
            f"!= {sorted(map(str, legacy[skill_id]))}"
            for skill_id in custom_ids
            if legacy[skill_id] != plugin_rows[skill_id]
        )
    return problems
