"""DB operations for plugins, their versions and marketplaces.

A version never changes. Each change to a plugin's files adds a version and
moves ``plugin.current_version_id``. In phase 1 a change to a plugin in the
Organization library also moves ``published_version_id``, so an edit reaches
the organization at once, as before plugins.

Access is on the plugin: shares, the install setting, the user choice and
publishing. ``apply_plugin_access_change__no_commit`` is the one write path
for shares, publishing and install settings, with one set of rules. Until the
legacy skill tables are dropped, it also writes the legacy skill rows of a
plugin that has one, in the same transaction.

Published means: in the Organization library. Publishing is one-way.

Lock order: a caller that also writes the legacy skill row locks that row
first, then these functions lock the plugin row. Many plugins are locked in id
order.

Functions here flush and never commit.
"""

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.configs.constants import FileOrigin
from onyx.db.enums import (
    MarketplaceKind,
    Permission,
    PluginInstallationPolicy,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    FileRecord,
    Marketplace,
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
    PluginSkill,
    PluginVersion,
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    UserPluginPreference,
    UserSkillPreference,
)
from onyx.db.plugin_access import affected_user_ids_for_plugins
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.db.utils import (
    UNSET,
    UnsetType,
    is_fk_violation,
    is_set,
    is_unique_violation,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.models import (
    PluginFileEntry,
    PluginSkillContent,
    PluginVersionContent,
)

# Same fixed id as the migration that made the plugin tables.
ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")
ORGANIZATION_LIBRARY_NAME = "Organization library"
USER_UPLOADS_NAME = "My uploads"
PLUGIN_NAME_MAX_LENGTH = 64

_PLUGIN_NAME_INDEX = "uq_plugin_marketplace_name"
_PLUGIN_PRIMARY_KEY = "plugin_pkey"

# The newest version keeps its bundle, with the newest older versions up to
# this many bundles. The published version always keeps its bundle too.
BUNDLES_KEPT = 10

NameClashAction = Literal["raise", "rename"]
_RENAME_ATTEMPTS = 3

PluginVersionKind = Literal["skill", "plugin"]


def plugin_version_kind(skill_paths: Iterable[str]) -> PluginVersionKind:
    """The kind of a version, from the paths of its plugin_skill rows. A
    version is a skill when it holds exactly one skill, with SKILL.md at the
    bundle root; otherwise it is a plugin. No column stores the result, so a
    later version can change it."""
    return "skill" if list(skill_paths) == [""] else "plugin"


def get_plugin_version_kind(version_id: UUID, db_session: Session) -> PluginVersionKind:
    return plugin_version_kind(
        db_session.scalars(
            select(PluginSkill.path).where(PluginSkill.plugin_version_id == version_id)
        )
    )


def user_uploads_marketplace_id(user_id: UUID) -> UUID:
    """Same id as SQL md5('user_uploads:' || user_id)::uuid."""
    digest = hashlib.md5(
        f"user_uploads:{user_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return UUID(digest)


def get_or_create_user_uploads__no_commit(user_id: UUID, db_session: Session) -> UUID:
    """Return the user's "My uploads" id. Two first uploads at the same time
    both work: the second insert waits for the first and then does nothing."""
    db_session.execute(
        insert(Marketplace)
        .values(
            id=user_uploads_marketplace_id(user_id),
            kind=MarketplaceKind.USER_UPLOADS,
            name=USER_UPLOADS_NAME,
            owner_user_id=user_id,
            default_installation_policy=PluginInstallationPolicy.AVAILABLE,
        )
        .on_conflict_do_nothing()
    )
    return db_session.scalars(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.USER_UPLOADS,
            Marketplace.owner_user_id == user_id,
        )
    ).one()


def get_or_create_organization_library__no_commit(db_session: Session) -> UUID:
    db_session.execute(
        insert(Marketplace)
        .values(
            id=ORGANIZATION_LIBRARY_ID,
            kind=MarketplaceKind.ORGANIZATION_LIBRARY,
            name=ORGANIZATION_LIBRARY_NAME,
            owner_user_id=None,
            default_installation_policy=PluginInstallationPolicy.AVAILABLE,
        )
        .on_conflict_do_nothing()
    )
    return db_session.scalars(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY
        )
    ).one()


def free_plugin_name(
    marketplace_id: UUID,
    name: str,
    db_session: Session,
) -> str:
    """The name, or else the first of name-2, name-3, ... that no plugin in the
    marketplace uses. The base is cut so the result fits 64 characters. Same
    rule as the plugin tables migration."""

    def is_taken(candidate: str) -> bool:
        return (
            db_session.scalar(
                select(Plugin.id).where(
                    Plugin.marketplace_id == marketplace_id,
                    Plugin.name == candidate,
                )
            )
            is not None
        )

    candidate = name
    suffix = 1
    while is_taken(candidate):
        suffix += 1
        base = name[: PLUGIN_NAME_MAX_LENGTH - 1 - len(str(suffix))]
        candidate = f"{base}-{suffix}"
    return candidate


def _add_version_rows(
    *,
    version_id: UUID,
    plugin_id: UUID,
    version_number: int,
    content: PluginVersionContent,
    created_by: User | None,
    db_session: Session,
) -> PluginVersion:
    version = PluginVersion(
        id=version_id,
        plugin_id=plugin_id,
        version_number=version_number,
        bundle_file_id=content.bundle_file_id,
        bundle_sha256=content.bundle_sha256,
        is_valid=content.is_valid,
        file_manifest=(
            [entry.model_dump() for entry in content.file_manifest]
            if content.file_manifest is not None
            else None
        ),
        unpacked_size_bytes=content.unpacked_size_bytes,
        file_count=content.file_count,
        created_by_user_id=created_by.id if created_by is not None else None,
        created_by_email=created_by.email if created_by is not None else None,
    )
    db_session.add(version)
    db_session.flush()
    db_session.add_all(
        PluginSkill(
            plugin_version_id=version.id,
            path=skill.path,
            skill_md=skill.skill_md,
            frontmatter=skill.frontmatter,
        )
        for skill in content.skills
    )
    db_session.flush()
    return version


def create_plugin__no_commit(
    *,
    plugin_id: UUID,
    name: str,
    marketplace_id: UUID,
    author_user_id: UUID | None,
    installation_policy: PluginInstallationPolicy | None,
    publish: bool,
    content: PluginVersionContent,
    created_by: User | None,
    db_session: Session,
) -> Plugin:
    """Add a plugin with version 1 and its plugin_skill rows. A used name
    takes the next free name. A plugin that takes the same name at the same
    time gets SKILL_NAME_CONFLICT."""
    description = (
        content.skills[0].description
        if plugin_version_kind(skill.path for skill in content.skills) == "skill"
        else ""
    )
    version_id = uuid4()
    try:
        with db_session.begin_nested():
            plugin = Plugin(
                id=plugin_id,
                name=free_plugin_name(marketplace_id, name, db_session),
                description=description,
                marketplace_id=marketplace_id,
                author_user_id=author_user_id,
                installation_policy=installation_policy,
                # Both pointer foreign keys are checked at the commit, after
                # the version exists.
                current_version_id=version_id,
                published_version_id=version_id if publish else None,
            )
            db_session.add(plugin)
            db_session.flush()
            _add_version_rows(
                version_id=version_id,
                plugin_id=plugin_id,
                version_number=1,
                content=content,
                created_by=created_by,
                db_session=db_session,
            )
    except IntegrityError as exc:
        if not is_unique_violation(exc, _PLUGIN_NAME_INDEX):
            raise
        raise OnyxError(
            OnyxErrorCode.SKILL_NAME_CONFLICT,
            f"Another skill named '{name}' was saved at the same time. Try again.",
        ) from exc
    return plugin


def lock_plugin(plugin_id: UUID, db_session: Session) -> Plugin | None:
    return db_session.scalars(
        select(Plugin)
        .where(Plugin.id == plugin_id)
        .with_for_update(of=Plugin)
        .execution_options(populate_existing=True)
    ).one_or_none()


def _manifest_matches(
    current: PluginVersion,
    content: PluginVersionContent,
    previous_manifest: Callable[[], list[PluginFileEntry]] | None,
) -> bool:
    if content.file_manifest is None:
        return current.bundle_sha256 == content.bundle_sha256
    new_manifest = [entry.model_dump() for entry in content.file_manifest]
    if current.file_manifest is not None:
        return current.file_manifest == new_manifest
    # A version from before file lists were written has none.
    if previous_manifest is not None:
        return [entry.model_dump() for entry in previous_manifest()] == new_manifest
    return current.bundle_sha256 == content.bundle_sha256


def _has_no_file_manifest() -> ColumnElement[bool]:
    # An ORM insert of None writes JSON null; the plugin backfill writes NULL.
    return or_(
        PluginVersion.file_manifest.is_(None),
        func.jsonb_typeof(PluginVersion.file_manifest) == "null",
    )


def prune_plugin_bundles__no_commit(plugin: Plugin, db_session: Session) -> list[str]:
    """Empty the bundle of each version that is not one of the newest
    ``BUNDLES_KEPT``, the current or the published version. The version rows
    stay. A bundle that the legacy skill row uses is kept, and so is the
    bundle of a version with no stored file list or root SKILL.md text,
    because reads of that version still open the bundle. Call under the
    plugin lock. Returns the files that nothing uses now; the caller deletes
    them after the commit."""
    kept = {
        version_id
        for version_id in (plugin.current_version_id, plugin.published_version_id)
        if version_id is not None
    }
    kept.update(
        db_session.scalars(
            select(PluginVersion.id)
            .where(PluginVersion.plugin_id == plugin.id)
            .order_by(PluginVersion.version_number.desc())
            .limit(BUNDLES_KEPT)
        )
    )
    legacy_bundle_file_id = db_session.scalar(
        select(Skill.bundle_file_id).where(Skill.id == plugin.id)
    )
    pruned: dict[UUID, str] = {
        version_id: file_id
        for version_id, file_id in db_session.execute(
            select(PluginVersion.id, PluginVersion.bundle_file_id).where(
                PluginVersion.plugin_id == plugin.id,
                PluginVersion.bundle_file_id.is_not(None),
                PluginVersion.id.not_in(kept),
                ~_has_no_file_manifest(),
                ~exists().where(
                    PluginSkill.plugin_version_id == PluginVersion.id,
                    PluginSkill.path == "",
                    PluginSkill.skill_md.is_(None),
                ),
            )
        ).tuples()
        if file_id is not None and file_id != legacy_bundle_file_id
    }
    if not pruned:
        return []
    db_session.execute(
        update(PluginVersion)
        .where(PluginVersion.id.in_(pruned.keys()))
        .values(bundle_file_id=None)
    )
    file_ids = set(pruned.values())
    still_used = set(
        db_session.scalars(
            select(PluginVersion.bundle_file_id).where(
                PluginVersion.bundle_file_id.in_(file_ids)
            )
        )
    )
    return sorted(file_ids - still_used)


@dataclass(frozen=True)
class AddedPluginVersion:
    version: PluginVersion
    # Bundles that retention pruned. Delete them after the commit.
    pruned_bundle_file_ids: list[str]


def add_plugin_version__no_commit(
    *,
    plugin: Plugin,
    content: PluginVersionContent,
    base_version_id: UUID | None,
    created_by: User | None,
    skip_if_unchanged: bool,
    db_session: Session,
    previous_manifest: Callable[[], list[PluginFileEntry]] | None = None,
) -> AddedPluginVersion | None:
    """Add the next version of a plugin locked with ``lock_plugin``, move its
    pointers and prune old bundles. Returns None, and writes nothing, when
    ``skip_if_unchanged`` is set and the files equal the current version's
    files.

    ``base_version_id`` is the version the edit started from. When given and
    not the current version, the edit is refused with PLUGIN_VERSION_STALE.
    ``previous_manifest`` supplies the current files when the current version
    has no file list yet."""
    if base_version_id is not None and base_version_id != plugin.current_version_id:
        raise OnyxError(
            OnyxErrorCode.PLUGIN_VERSION_STALE,
            "This skill changed since you opened it. Reload it to get the "
            "newest version, then make your change again.",
        )
    current = db_session.get(PluginVersion, plugin.current_version_id)
    if current is None:
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Plugin has no current version.")

    if get_plugin_version_kind(current.id, db_session) == "skill":
        current_names = sorted(
            db_session.scalars(
                select(PluginSkill.frontmatter["name"].astext).where(
                    PluginSkill.plugin_version_id == current.id
                )
            )
        )
        new_names = sorted(skill.name for skill in content.skills)
        if current_names and new_names != current_names:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Replacement SKILL.md frontmatter field 'name' must remain "
                f"'{current_names[0]}'",
            )

    if skip_if_unchanged and _manifest_matches(current, content, previous_manifest):
        return None

    next_number = (
        db_session.scalar(
            select(func.max(PluginVersion.version_number)).where(
                PluginVersion.plugin_id == plugin.id
            )
        )
        or 0
    ) + 1
    version = _add_version_rows(
        version_id=uuid4(),
        plugin_id=plugin.id,
        version_number=next_number,
        content=content,
        created_by=created_by,
        db_session=db_session,
    )
    plugin.current_version_id = version.id
    marketplace_kind = db_session.scalar(
        select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
    )
    if marketplace_kind == MarketplaceKind.ORGANIZATION_LIBRARY:
        plugin.published_version_id = version.id
    if plugin_version_kind(skill.path for skill in content.skills) == "skill":
        plugin.description = content.skills[0].description
    db_session.flush()
    return AddedPluginVersion(
        version=version,
        pruned_bundle_file_ids=prune_plugin_bundles__no_commit(plugin, db_session),
    )


@dataclass(frozen=True)
class StoredVersionContent:
    """What the database holds of one version's content. ``file_manifest`` and
    ``skill_md`` are None for a version copied from a legacy skill row before
    the repair task fills them."""

    version_id: UUID
    bundle_file_id: str | None
    # Name in the frontmatter of the skill at the bundle root.
    name: str | None
    file_manifest: list[PluginFileEntry] | None
    skill_md: str | None


def get_stored_version_content(
    version_id: UUID, db_session: Session
) -> StoredVersionContent | None:
    row = db_session.execute(
        select(
            PluginVersion.bundle_file_id,
            PluginSkill.frontmatter["name"].astext,
            PluginVersion.file_manifest,
            PluginSkill.skill_md,
        )
        .outerjoin(
            PluginSkill,
            and_(
                PluginSkill.plugin_version_id == PluginVersion.id,
                PluginSkill.path == "",
            ),
        )
        .where(PluginVersion.id == version_id)
    ).one_or_none()
    if row is None:
        return None
    bundle_file_id, name, manifest, skill_md = row
    return StoredVersionContent(
        version_id=version_id,
        bundle_file_id=bundle_file_id,
        name=name,
        file_manifest=(
            [PluginFileEntry.model_validate(entry) for entry in manifest]
            if manifest is not None
            else None
        ),
        skill_md=skill_md,
    )


def get_plugin_current_version_id(plugin_id: UUID, db_session: Session) -> UUID | None:
    return db_session.scalar(
        select(Plugin.current_version_id).where(Plugin.id == plugin_id)
    )


def get_current_version_bundle_file_id(
    plugin_id: UUID, db_session: Session
) -> str | None:
    return db_session.scalar(
        select(PluginVersion.bundle_file_id)
        .join(Plugin, Plugin.current_version_id == PluginVersion.id)
        .where(Plugin.id == plugin_id)
    )


PluginVersionPointer = Literal["current", "organization"]


def get_plugin_version_validity(
    plugin_ids: Iterable[UUID],
    pointer: PluginVersionPointer,
    db_session: Session,
) -> dict[UUID, bool | None]:
    """``is_valid`` of one version of each plugin: the current version, or the
    version the organization runs (published, else current)."""
    ids = set(plugin_ids)
    if not ids:
        return {}
    version_id = (
        Plugin.current_version_id
        if pointer == "current"
        else func.coalesce(Plugin.published_version_id, Plugin.current_version_id)
    )
    rows = db_session.execute(
        select(Plugin.id, PluginVersion.is_valid)
        .join(PluginVersion, PluginVersion.id == version_id)
        .where(Plugin.id.in_(ids))
    ).tuples()
    return dict(rows.all())


def delete_plugin__no_commit(plugin_id: UUID, db_session: Session) -> list[str]:
    """Delete a plugin with its versions, skills, shares and choices. Returns
    the bundle files of its versions; the caller deletes them after the
    commit."""
    bundle_file_ids = db_session.scalars(
        select(PluginVersion.bundle_file_id)
        .where(
            PluginVersion.plugin_id == plugin_id,
            PluginVersion.bundle_file_id.is_not(None),
        )
        .distinct()
    ).all()
    db_session.execute(delete(Plugin).where(Plugin.id == plugin_id))
    return [file_id for file_id in bundle_file_ids if file_id is not None]


def persist_plugin_version_validity__no_commit(
    *,
    plugin_id: UUID,
    bundle_file_id: str | None,
    is_valid: bool,
    db_session: Session,
) -> None:
    """Classify the plugin's unclassified versions that hold this bundle."""
    if bundle_file_id is None:
        return
    db_session.execute(
        update(PluginVersion)
        .where(
            PluginVersion.plugin_id == plugin_id,
            PluginVersion.bundle_file_id == bundle_file_id,
            PluginVersion.is_valid.is_(None),
        )
        .values(is_valid=is_valid)
    )


# An upload saves its bundle before the row that uses it commits.
ORPHAN_BUNDLE_MIN_AGE = timedelta(hours=1)


def get_orphan_skill_bundle_file_ids(
    *, after_file_id: str | None, limit: int, db_session: Session
) -> list[str]:
    """Skill bundle files older than ``ORPHAN_BUNDLE_MIN_AGE`` that no plugin
    version and no legacy skill row uses, in file id order."""
    statement = (
        select(FileRecord.file_id)
        .where(
            FileRecord.file_origin == FileOrigin.SKILL_BUNDLE,
            FileRecord.created_at < func.now() - ORPHAN_BUNDLE_MIN_AGE,
            ~exists().where(PluginVersion.bundle_file_id == FileRecord.file_id),
            ~exists().where(Skill.bundle_file_id == FileRecord.file_id),
        )
        .order_by(FileRecord.file_id)
        .limit(limit)
    )
    if after_file_id is not None:
        statement = statement.where(FileRecord.file_id > after_file_id)
    return list(db_session.scalars(statement))


@dataclass(frozen=True)
class VersionToRepair:
    version_id: UUID
    bundle_file_id: str
    # Name in the frontmatter of the skill at the bundle root.
    name: str


def get_plugin_versions_to_repair(
    *,
    after_version_id: UUID | None,
    skip_version_ids: Iterable[UUID],
    limit: int,
    db_session: Session,
) -> list[VersionToRepair]:
    """Versions copied from a legacy skill row that still have no file list:
    they have a bundle and are not known to be invalid. In id order."""
    statement = (
        select(
            PluginVersion.id,
            PluginVersion.bundle_file_id,
            PluginSkill.frontmatter["name"].astext,
        )
        .join(
            PluginSkill,
            and_(
                PluginSkill.plugin_version_id == PluginVersion.id,
                PluginSkill.path == "",
            ),
        )
        .where(
            _has_no_file_manifest(),
            PluginVersion.bundle_file_id.is_not(None),
            PluginVersion.is_valid.is_not(False),
        )
        .order_by(PluginVersion.id)
        .limit(limit)
    )
    if after_version_id is not None:
        statement = statement.where(PluginVersion.id > after_version_id)
    skip = set(skip_version_ids)
    if skip:
        statement = statement.where(PluginVersion.id.not_in(skip))
    return [
        VersionToRepair(version_id=version_id, bundle_file_id=file_id, name=name)
        for version_id, file_id, name in db_session.execute(statement).tuples()
        if file_id is not None
    ]


def repair_plugin_version__no_commit(
    *,
    version_id: UUID,
    bundle_file_id: str,
    content: PluginVersionContent,
    db_session: Session,
) -> bool:
    """Fill the file list, sizes and root skill content of a version copied
    from a legacy skill row, and mark it valid when it is unclassified. Does
    nothing, and returns False, when the version has a file list already or no
    longer holds this bundle."""
    updated = db_session.execute(
        update(PluginVersion)
        .where(
            PluginVersion.id == version_id,
            PluginVersion.bundle_file_id == bundle_file_id,
            _has_no_file_manifest(),
        )
        .values(
            file_manifest=(
                [entry.model_dump() for entry in content.file_manifest]
                if content.file_manifest is not None
                else None
            ),
            unpacked_size_bytes=content.unpacked_size_bytes,
            file_count=content.file_count,
            is_valid=func.coalesce(PluginVersion.is_valid, True),
        )
        .returning(PluginVersion.id)
    ).scalar_one_or_none()
    if updated is None:
        return False
    root = content.skills[0]
    db_session.execute(
        update(PluginSkill)
        .where(
            PluginSkill.plugin_version_id == version_id,
            PluginSkill.path == root.path,
        )
        .values(skill_md=root.skill_md, frontmatter=root.frontmatter)
    )
    return True


def mark_plugin_version_invalid__no_commit(
    *, version_id: UUID, bundle_file_id: str, db_session: Session
) -> None:
    db_session.execute(
        update(PluginVersion)
        .where(
            PluginVersion.id == version_id,
            PluginVersion.bundle_file_id == bundle_file_id,
        )
        .values(is_valid=False)
    )


# --- Skill plugins and their access ----------------------------------------


def plugin_installation_policy(
    policy: SkillInstallationPolicy,
) -> PluginInstallationPolicy | None:
    """Legacy AVAILABLE maps to NULL, so the plugin follows its marketplace
    default. DEFAULT and REQUIRED map as they are."""
    if policy == SkillInstallationPolicy.AVAILABLE:
        return None
    return PluginInstallationPolicy(policy.value)


def legacy_skill_version_content(skill: Skill) -> PluginVersionContent:
    """Version 1 of a plugin made from a legacy skill row, as the plugin
    backfill makes it: the row's bundle, with no file list or SKILL.md text."""
    if skill.bundle_file_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' has no bundle.",
        )
    return PluginVersionContent(
        bundle_file_id=skill.bundle_file_id,
        bundle_sha256=skill.bundle_sha256,
        is_valid=skill.is_valid,
        file_manifest=None,
        unpacked_size_bytes=None,
        file_count=None,
        skills=[
            PluginSkillContent(
                path="",
                skill_md=None,
                frontmatter={"name": skill.name, "description": skill.description},
            )
        ],
    )


def create_skill_plugin__no_commit(
    skill: Skill,
    content: PluginVersionContent,
    created_by: User | None,
    db_session: Session,
) -> Plugin:
    """Add the plugin of a custom skill with ``content`` as version 1. A public
    or author-less skill goes to the Organization library, published; others
    go to the author's "My uploads". Same placement as the plugin backfill."""
    author_user_id = skill.author_user_id
    publish = skill.public_permission is not None or author_user_id is None
    if author_user_id is None or publish:
        marketplace_id = get_or_create_organization_library__no_commit(db_session)
    else:
        marketplace_id = get_or_create_user_uploads__no_commit(
            author_user_id, db_session
        )
    return create_plugin__no_commit(
        plugin_id=skill.id,
        name=skill.name,
        marketplace_id=marketplace_id,
        author_user_id=author_user_id,
        installation_policy=plugin_installation_policy(skill.installation_policy),
        publish=publish,
        content=content,
        created_by=created_by,
        db_session=db_session,
    )


def _copy_legacy_access__no_commit(skill_id: UUID, db_session: Session) -> None:
    db_session.execute(
        insert(Plugin__User)
        .from_select(
            ["plugin_id", "user_id", "permission"],
            select(Skill__User.skill_id, Skill__User.user_id, Skill__User.permission)
            .where(Skill__User.skill_id == skill_id)
            .order_by(Skill__User.user_id),
        )
        .on_conflict_do_nothing()
    )
    db_session.execute(
        insert(Plugin__UserGroup)
        .from_select(
            ["plugin_id", "user_group_id", "permission"],
            select(
                Skill__UserGroup.skill_id,
                Skill__UserGroup.user_group_id,
                Skill__UserGroup.permission,
            )
            .where(Skill__UserGroup.skill_id == skill_id)
            .order_by(Skill__UserGroup.user_group_id),
        )
        .on_conflict_do_nothing()
    )
    db_session.execute(
        insert(UserPluginPreference)
        .from_select(
            ["user_id", "plugin_id", "enabled"],
            select(
                UserSkillPreference.user_id,
                UserSkillPreference.skill_id,
                UserSkillPreference.enabled,
            )
            .where(UserSkillPreference.skill_id == skill_id)
            .order_by(UserSkillPreference.user_id),
        )
        .on_conflict_do_nothing()
    )


def lock_skill_plugin__no_commit(skill: Skill, db_session: Session) -> Plugin:
    """Lock and return the plugin of a custom skill. The caller holds the skill
    row lock, or the skill is new in this transaction.

    A skill can have no plugin: an older server made it, or a user delete
    removed a stale copy. It first gets one copied from its legacy rows, as the
    plugin backfill does: version 1 with the current bundle, the placement,
    owner, install setting, shares and choices. Call this before any change to
    the legacy rows, so the copy is the state before the change."""
    plugin = lock_plugin(skill.id, db_session)
    if plugin is not None:
        return plugin
    try:
        with db_session.begin_nested():
            create_skill_plugin__no_commit(
                skill, legacy_skill_version_content(skill), skill.author, db_session
            )
            _copy_legacy_access__no_commit(skill.id, db_session)
    except IntegrityError as exc:
        # Another transaction made the plugin first. Use that one.
        if not is_unique_violation(exc, _PLUGIN_PRIMARY_KEY):
            raise
    plugin = lock_plugin(skill.id, db_session)
    if plugin is None:
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Plugin was not saved.")
    return plugin


def _preferred_name(plugin: Plugin, db_session: Session) -> str:
    """The name a plugin asks for in a marketplace: for a plugin whose current
    version is a skill, its skill name, which a "-2" suffix in the old
    marketplace does not change."""
    rows = db_session.execute(
        select(PluginSkill.path, PluginSkill.frontmatter["name"].astext).where(
            PluginSkill.plugin_version_id == plugin.current_version_id
        )
    ).all()
    if plugin_version_kind(path for path, _ in rows) == "skill" and rows[0][1]:
        return rows[0][1]
    return plugin.name


def _move_plugin__no_commit(
    *,
    plugin: Plugin,
    marketplace_id: UUID,
    on_name_clash: NameClashAction,
    clash_detail: Callable[[str], str],
    db_session: Session,
) -> None:
    preferred = _preferred_name(plugin, db_session)
    # A concurrent writer can take the chosen name before this move commits.
    # "rename" then picks the next free name again.
    for attempt in range(1, _RENAME_ATTEMPTS + 1):
        name = preferred
        name_taken = (
            db_session.scalar(
                select(Plugin.id).where(
                    Plugin.marketplace_id == marketplace_id,
                    Plugin.name == name,
                    Plugin.id != plugin.id,
                )
            )
            is not None
        )
        if name_taken:
            if on_name_clash == "raise":
                raise OnyxError(OnyxErrorCode.CONFLICT, clash_detail(name))
            name = free_plugin_name(marketplace_id, name, db_session)
        try:
            with db_session.begin_nested():
                plugin.marketplace_id = marketplace_id
                plugin.name = name
                db_session.flush()
            return
        except IntegrityError as exc:
            if not is_unique_violation(exc, _PLUGIN_NAME_INDEX):
                raise
            if on_name_clash == "raise" or attempt == _RENAME_ATTEMPTS:
                raise OnyxError(OnyxErrorCode.CONFLICT, clash_detail(name)) from exc


def _organization_name_clash(name: str) -> str:
    return (
        f"The organization already has a published skill named '{name}'. "
        "Two published skills cannot use the same name."
    )


def publish_plugin__no_commit(
    plugin_id: UUID,
    on_name_clash: NameClashAction,
    db_session: Session,
) -> None:
    """Publish a plugin to the organization: move it to the Organization library
    and set published_version_id to current_version_id. Publishing is one-way.
    A plugin that is already in the Organization library does not change.

    On a name clash in the Organization library, "raise" refuses with CONFLICT
    and "rename" takes the next free name (deploy-2)."""
    plugin = lock_plugin(plugin_id, db_session)
    if plugin is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
    library_id = get_or_create_organization_library__no_commit(db_session)
    if plugin.marketplace_id == library_id:
        return
    _move_plugin__no_commit(
        plugin=plugin,
        marketplace_id=library_id,
        on_name_clash=on_name_clash,
        clash_detail=_organization_name_clash,
        db_session=db_session,
    )
    plugin.published_version_id = plugin.current_version_id
    db_session.flush()


def is_plugin_published(plugin: Plugin, db_session: Session) -> bool:
    return (
        db_session.scalar(
            select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
        )
        == MarketplaceKind.ORGANIZATION_LIBRARY
    )


def transfer_plugin__no_commit(
    plugin_id: UUID,
    new_author_user_id: UUID,
    db_session: Session,
) -> None:
    """Set the plugin's author. A private plugin also moves to the new owner's
    "My uploads"; a name clash there is refused with CONFLICT. A published
    plugin stays in the Organization library."""
    plugin = lock_plugin(plugin_id, db_session)
    if plugin is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
    if not is_plugin_published(plugin, db_session):
        _move_plugin__no_commit(
            plugin=plugin,
            marketplace_id=get_or_create_user_uploads__no_commit(
                new_author_user_id, db_session
            ),
            on_name_clash="raise",
            clash_detail=lambda name: (
                f"The new owner already has a skill named '{name}'. "
                "Ask them to delete or rename it first."
            ),
            db_session=db_session,
        )
    plugin.author_user_id = new_author_user_id
    db_session.flush()


def set_plugin_installation_policy__no_commit(
    plugin_id: UUID,
    policy: SkillInstallationPolicy,
    db_session: Session,
) -> None:
    """Mirror of the legacy company install setting."""
    db_session.execute(
        update(Plugin)
        .where(Plugin.id == plugin_id)
        .values(installation_policy=plugin_installation_policy(policy))
    )


def replace_plugin_user_shares__no_commit(
    plugin_id: UUID,
    shares: Mapping[UUID, SkillSharePermission],
    db_session: Session,
) -> None:
    """Mirror of the legacy user shares. A kept share keeps its created_at."""
    db_session.execute(
        delete(Plugin__User).where(
            Plugin__User.plugin_id == plugin_id,
            Plugin__User.user_id.notin_(list(shares)),
        )
    )
    if not shares:
        return
    stmt = insert(Plugin__User).values(
        [
            {"plugin_id": plugin_id, "user_id": user_id, "permission": permission}
            for user_id, permission in sorted(shares.items())
        ]
    )
    db_session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Plugin__User.plugin_id, Plugin__User.user_id],
            set_={"permission": stmt.excluded.permission},
        )
    )


@dataclass(frozen=True)
class PluginGroupRow:
    """The state of one plugin__user_group row. No permission: the row holds
    only a group install setting and grants no access."""

    permission: SkillSharePermission | None
    installation_policy: PluginInstallationPolicy | None


def replace_plugin_group_rows__no_commit(
    plugin_id: UUID,
    rows: Mapping[int, PluginGroupRow],
    db_session: Session,
) -> None:
    """Make the plugin's group rows equal ``rows``. A kept row keeps its
    created_at."""
    db_session.execute(
        delete(Plugin__UserGroup).where(
            Plugin__UserGroup.plugin_id == plugin_id,
            Plugin__UserGroup.user_group_id.notin_(list(rows)),
        )
    )
    if not rows:
        return
    stmt = insert(Plugin__UserGroup).values(
        [
            {
                "plugin_id": plugin_id,
                "user_group_id": group_id,
                "permission": row.permission,
                "installation_policy": row.installation_policy,
            }
            for group_id, row in sorted(rows.items())
        ]
    )
    db_session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                Plugin__UserGroup.plugin_id,
                Plugin__UserGroup.user_group_id,
            ],
            set_={
                "permission": stmt.excluded.permission,
                "installation_policy": stmt.excluded.installation_policy,
            },
        )
    )


def set_plugin_preferences__no_commit(
    user_id: UUID,
    plugin_ids: Iterable[UUID],
    enabled: bool,
    db_session: Session,
) -> None:
    """Mirror of the legacy user on/off choice. enabled_at is set each time the
    user turns a plugin on."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return
    enabled_at = func.now() if enabled else None
    stmt = insert(UserPluginPreference).values(
        [
            {
                "user_id": user_id,
                "plugin_id": plugin_id,
                "enabled": enabled,
                "enabled_at": enabled_at,
            }
            for plugin_id in ids
        ]
    )
    db_session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                UserPluginPreference.user_id,
                UserPluginPreference.plugin_id,
            ],
            set_={
                "enabled": stmt.excluded.enabled,
                "enabled_at": (
                    func.now() if enabled else UserPluginPreference.enabled_at
                ),
            },
        )
    )


def delete_plugin_preferences__no_commit(
    plugin_ids: Iterable[UUID],
    db_session: Session,
    *,
    user_id: UUID | None = None,
    enabled_only: bool = False,
) -> None:
    """Mirror of a legacy delete of user choices."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return
    stmt = delete(UserPluginPreference).where(UserPluginPreference.plugin_id.in_(ids))
    if user_id is not None:
        stmt = stmt.where(UserPluginPreference.user_id == user_id)
    if enabled_only:
        stmt = stmt.where(UserPluginPreference.enabled.is_(True))
    db_session.execute(stmt)


# --- Access changes ----------------------------------------------------------


class PluginAccessMode(str, Enum):
    """REPLACE: the supplied grants are the new set. ADD_ONLY: the supplied
    grants are added to the current ones or change their level; no grant is
    removed."""

    REPLACE = "replace"
    ADD_ONLY = "add_only"


@dataclass(frozen=True)
class PluginUserGrant:
    user_id: UUID
    permission: SkillSharePermission


@dataclass(frozen=True)
class PluginGroupGrant:
    group_id: int
    permission: SkillSharePermission
    # UNSET keeps the group's install setting. None removes it.
    installation_policy: PluginInstallationPolicy | None | UnsetType = UNSET


@dataclass(frozen=True)
class PluginAccessChange:
    """One access change for one or more plugins. A field at its default does
    not change anything.

    ``company_installation_policy``: UNSET keeps it, None means "use the
    marketplace default", and a value sets that value."""

    user_grants: tuple[PluginUserGrant, ...] | None = None
    group_grants: tuple[PluginGroupGrant, ...] | None = None
    publish: bool = False
    company_installation_policy: PluginInstallationPolicy | None | UnsetType = UNSET
    mode: PluginAccessMode = PluginAccessMode.REPLACE


@dataclass(frozen=True)
class PluginAccessResult:
    """``affected_user_ids``: users with a running sandbox who could see one
    of the plugins before or after the change. ``failures``: plugins whose
    change was refused or failed and rolled back."""

    affected_user_ids: set[UUID]
    failures: dict[UUID, OnyxError]

    def raise_first_failure(self) -> None:
        for plugin_id in sorted(self.failures):
            raise self.failures[plugin_id]


@dataclass
class _LockedPlugin:
    plugin: Plugin
    # The legacy skill row with the same id, while the skill tables exist.
    skill: Skill | None
    published: bool
    user_grants: dict[UUID, SkillSharePermission]
    group_rows: dict[int, PluginGroupRow]


_USER_TARGET_MISSING = "One or more user share targets do not exist."
_GROUP_TARGET_MISSING = "One or more group share targets do not exist."


def _lock_for_access_change(
    ids: list[UUID], db_session: Session
) -> tuple[dict[UUID, _LockedPlugin], dict[UUID, OnyxError]]:
    """Lock the legacy skill rows, then the plugins, each in id order, and
    read their current grants. A skill with no plugin gets one first."""
    skills = {
        skill.id: skill
        for skill in db_session.scalars(
            select(Skill)
            .where(Skill.id.in_(ids), Skill.built_in_skill_id.is_(None))
            .order_by(Skill.id)
            .with_for_update(of=Skill)
        )
    }
    plugins: dict[UUID, Plugin] = {}
    missing: dict[UUID, OnyxError] = {}
    for plugin_id in ids:
        skill = skills.get(plugin_id)
        plugin = (
            lock_skill_plugin__no_commit(skill, db_session)
            if skill is not None
            else lock_plugin(plugin_id, db_session)
        )
        if plugin is None:
            missing[plugin_id] = OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
        else:
            plugins[plugin_id] = plugin
    found = list(plugins)
    published = set(
        db_session.scalars(
            select(Plugin.id)
            .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
            .where(
                Plugin.id.in_(found),
                Marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY,
            )
        )
    )
    user_grants: dict[UUID, dict[UUID, SkillSharePermission]] = {}
    for plugin_id, user_id, permission in db_session.execute(
        select(Plugin__User.plugin_id, Plugin__User.user_id, Plugin__User.permission)
        .where(Plugin__User.plugin_id.in_(found))
        .order_by(Plugin__User.plugin_id, Plugin__User.user_id)
    ):
        user_grants.setdefault(plugin_id, {})[user_id] = permission
    group_rows: dict[UUID, dict[int, PluginGroupRow]] = {}
    for plugin_id, group_id, permission, policy in db_session.execute(
        select(
            Plugin__UserGroup.plugin_id,
            Plugin__UserGroup.user_group_id,
            Plugin__UserGroup.permission,
            Plugin__UserGroup.installation_policy,
        )
        .where(Plugin__UserGroup.plugin_id.in_(found))
        .order_by(Plugin__UserGroup.plugin_id, Plugin__UserGroup.user_group_id)
    ):
        group_rows.setdefault(plugin_id, {})[group_id] = PluginGroupRow(
            permission=permission, installation_policy=policy
        )
    return {
        plugin_id: _LockedPlugin(
            plugin=plugin,
            skill=skills.get(plugin_id),
            published=plugin_id in published,
            user_grants=user_grants.get(plugin_id, {}),
            group_rows=group_rows.get(plugin_id, {}),
        )
        for plugin_id, plugin in plugins.items()
    }, missing


def _new_user_grants(
    locked: _LockedPlugin, change: PluginAccessChange
) -> dict[UUID, SkillSharePermission] | None:
    """The user grants after the change, or None when they do not change. The
    author never has a grant."""
    if change.user_grants is None:
        return None
    requested = {grant.user_id: grant.permission for grant in change.user_grants}
    grants = (
        requested
        if change.mode == PluginAccessMode.REPLACE
        else locked.user_grants | requested
    )
    return {
        user_id: permission
        for user_id, permission in grants.items()
        if user_id != locked.plugin.author_user_id
    }


def _new_group_rows(
    locked: _LockedPlugin, change: PluginAccessChange
) -> dict[int, PluginGroupRow] | None:
    """The group rows after the change, or None when they do not change. A
    group keeps its install setting unless the grant sets one. On REPLACE, a
    group left out loses its permission but keeps its row if it has a
    setting."""
    if change.group_grants is None:
        return None
    rows: dict[int, PluginGroupRow] = {}
    for group_id, row in locked.group_rows.items():
        if change.mode == PluginAccessMode.ADD_ONLY:
            rows[group_id] = row
        elif row.installation_policy is not None:
            rows[group_id] = PluginGroupRow(
                permission=None, installation_policy=row.installation_policy
            )
    for grant in change.group_grants:
        current = locked.group_rows.get(grant.group_id)
        rows[grant.group_id] = PluginGroupRow(
            permission=grant.permission,
            installation_policy=(
                grant.installation_policy
                if is_set(grant.installation_policy)
                else (current.installation_policy if current is not None else None)
            ),
        )
    return rows


def _group_shares(
    rows: Mapping[int, PluginGroupRow],
) -> dict[int, SkillSharePermission]:
    return {
        group_id: row.permission
        for group_id, row in rows.items()
        if row.permission is not None
    }


def _check_access_change(
    plugins: Mapping[UUID, _LockedPlugin],
    change: PluginAccessChange,
    actor: User | None,
    db_session: Session,
) -> None:
    """The checks that apply to the whole set. They raise before any write."""
    if (
        actor is not None
        and is_set(change.company_installation_policy)
        and not has_global_permission(actor, Permission.MANAGE_PLUGINS)
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide skill manager can change the install setting.",
        )
    if change.group_grants is None:
        return
    requested_group_ids = sorted({grant.group_id for grant in change.group_grants})
    assert_not_shared_with_default_group(db_session, requested_group_ids)

    any_published = change.publish or any(
        locked.published for locked in plugins.values()
    )
    setting_group_ids = sorted(
        {
            grant.group_id
            for grant in change.group_grants
            if is_set(grant.installation_policy)
        }
    )
    if setting_group_ids:
        if actor is not None:
            if any_published:
                if not has_global_permission(actor, Permission.MANAGE_PLUGINS):
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Only an organization-wide skill manager can set a "
                        "group install setting on a published skill.",
                    )
            else:
                assert_within_scope(
                    actor,
                    db_session,
                    permission=Permission.MANAGE_PLUGINS,
                    current_group_ids=[],
                    requested_group_ids=setting_group_ids,
                    is_non_public=True,
                )
        # The legacy group table has no install setting column.
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Group install settings are not available yet.",
        )

    # A change to a plugin's group shares is a MANAGE_PLUGINS action. The
    # current shares come from the database, never the request, so a
    # reassignment cannot escape scope. Re-sending the current set is no change.
    changed = [
        locked
        for locked in plugins.values()
        if _group_shares(_new_group_rows(locked, change) or {})
        != _group_shares(locked.group_rows)
    ]
    if actor is None or not changed:
        return
    assert_within_scope(
        actor,
        db_session,
        permission=Permission.MANAGE_PLUGINS,
        current_group_ids=sorted(
            {
                group_id
                for locked in changed
                for group_id in _group_shares(locked.group_rows)
            }
        ),
        requested_group_ids=requested_group_ids,
        is_non_public=not change.publish
        and not any(locked.published for locked in changed),
    )


def _legacy_installation_policy(
    policy: PluginInstallationPolicy | None,
) -> SkillInstallationPolicy:
    if policy is None or policy == PluginInstallationPolicy.AVAILABLE:
        return SkillInstallationPolicy.AVAILABLE
    if policy == PluginInstallationPolicy.NOT_AVAILABLE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A skill cannot be set to Not available yet.",
        )
    return SkillInstallationPolicy(policy.value)


def _write_user_grants__no_commit(
    locked: _LockedPlugin,
    grants: Mapping[UUID, SkillSharePermission],
    db_session: Session,
) -> None:
    plugin_id = locked.plugin.id
    try:
        with db_session.begin_nested():
            if locked.skill is not None:
                db_session.execute(
                    delete(Skill__User).where(
                        Skill__User.skill_id == plugin_id,
                        Skill__User.user_id.notin_(list(grants)),
                    )
                )
                if grants:
                    stmt = insert(Skill__User).values(
                        [
                            {
                                "skill_id": plugin_id,
                                "user_id": user_id,
                                "permission": permission,
                            }
                            for user_id, permission in sorted(grants.items())
                        ]
                    )
                    db_session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=[Skill__User.skill_id, Skill__User.user_id],
                            set_={"permission": stmt.excluded.permission},
                        )
                    )
            replace_plugin_user_shares__no_commit(plugin_id, grants, db_session)
    except IntegrityError as exc:
        if is_fk_violation(exc):
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, _USER_TARGET_MISSING) from exc
        raise
    if locked.skill is not None:
        db_session.expire(locked.skill, ["user_shares"])


def _write_group_rows__no_commit(
    locked: _LockedPlugin,
    rows: Mapping[int, PluginGroupRow],
    db_session: Session,
) -> None:
    plugin_id = locked.plugin.id
    shares = _group_shares(rows)
    try:
        with db_session.begin_nested():
            if locked.skill is not None:
                db_session.execute(
                    delete(Skill__UserGroup).where(
                        Skill__UserGroup.skill_id == plugin_id,
                        Skill__UserGroup.user_group_id.notin_(list(shares)),
                    )
                )
                if shares:
                    stmt = insert(Skill__UserGroup).values(
                        [
                            {
                                "skill_id": plugin_id,
                                "user_group_id": group_id,
                                "permission": permission,
                            }
                            for group_id, permission in sorted(shares.items())
                        ]
                    )
                    db_session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=[
                                Skill__UserGroup.skill_id,
                                Skill__UserGroup.user_group_id,
                            ],
                            set_={"permission": stmt.excluded.permission},
                        )
                    )
            replace_plugin_group_rows__no_commit(plugin_id, rows, db_session)
    except IntegrityError as exc:
        if is_fk_violation(exc):
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, _GROUP_TARGET_MISSING) from exc
        raise
    if locked.skill is not None:
        db_session.expire(locked.skill, ["group_shares"])


def _apply_to_plugin__no_commit(
    locked: _LockedPlugin,
    change: PluginAccessChange,
    actor: User | None,
    db_session: Session,
) -> None:
    plugin = locked.plugin
    skill = locked.skill
    if change.publish:
        # Until the Publishing setting: the author or an organization-wide
        # manager publishes.
        if (
            actor is not None
            and plugin.author_user_id != actor.id
            and not has_global_permission(actor, Permission.MANAGE_PLUGINS)
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "You do not have permission to change organization-wide skill access.",
            )
        if skill is not None and skill.public_permission is None:
            skill.public_permission = SkillSharePermission.VIEWER
            db_session.flush()
        publish_plugin__no_commit(plugin.id, "raise", db_session)

    if is_set(change.company_installation_policy):
        policy = change.company_installation_policy
        if skill is not None:
            try:
                with db_session.begin_nested():
                    skill.installation_policy = _legacy_installation_policy(policy)
                    db_session.flush()
            except IntegrityError as exc:
                if not is_unique_violation(exc, "uq_skill_automatic_name"):
                    raise
                raise OnyxError(
                    OnyxErrorCode.SKILL_NAME_CONFLICT,
                    "Another automatically installed skill already uses this name.",
                ) from exc
        plugin.installation_policy = policy
        db_session.flush()

    user_grants = _new_user_grants(locked, change)
    if user_grants is not None:
        _write_user_grants__no_commit(locked, user_grants, db_session)
    group_rows = _new_group_rows(locked, change)
    if group_rows is not None:
        _write_group_rows__no_commit(locked, group_rows, db_session)


def apply_plugin_access_change__no_commit(
    plugin_ids: Iterable[UUID],
    change: PluginAccessChange,
    actor: User | None,
    db_session: Session,
) -> PluginAccessResult:
    """The one write path for shares, publishing and install settings.

    Locks the legacy skill rows, then the plugins, in id order. Checks the
    rules once for the set and raises before any write when one fails. Then
    writes each plugin in its own savepoint, with its legacy skill rows: a
    refusal or failure on one plugin rolls back that plugin only and lands in
    ``failures``. The affected users are read for the whole set before and
    after the writes. The caller commits, then pushes once.

    Rules: a company install setting needs organization-wide MANAGE_PLUGINS. A
    group install setting needs MANAGE_PLUGINS for that group on a private
    plugin, and organization-wide MANAGE_PLUGINS on a published one; it is
    refused after these checks until the legacy group table is gone. A change
    to group shares must stay within the actor's managed scope. Publishing
    needs the author or organization-wide MANAGE_PLUGINS.

    ``actor`` None is a system write that the caller authorized, such as an
    ownership transfer. The permission checks are skipped; the other rules
    still apply."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return PluginAccessResult(affected_user_ids=set(), failures={})
    plugins, failures = _lock_for_access_change(ids, db_session)
    _check_access_change(plugins, change, actor, db_session)

    before = affected_user_ids_for_plugins(plugins, db_session)
    for plugin_id, locked in plugins.items():
        try:
            with db_session.begin_nested():
                _apply_to_plugin__no_commit(locked, change, actor, db_session)
        except OnyxError as exc:
            failures[plugin_id] = exc
    after = affected_user_ids_for_plugins(plugins, db_session)
    return PluginAccessResult(affected_user_ids=before | after, failures=failures)
