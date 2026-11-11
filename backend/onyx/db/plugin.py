"""DB operations for plugins, their versions and marketplaces.

A version never changes. Each change to a plugin's files adds a version and
moves ``plugin.current_version_id``. In phase 1 a change to a plugin in the
Organization library also moves ``published_version_id``, so an edit reaches
the organization at once, as before plugins.

Lock order: a caller that also writes the legacy skill row locks that row
first, then these functions lock the plugin row.

Functions here flush and never commit.
"""

import hashlib
from collections.abc import Callable, Iterable, Mapping
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import MarketplaceKind, PluginInstallationPolicy
from onyx.db.models import Marketplace, Plugin, PluginSkill, PluginVersion, User
from onyx.db.utils import is_unique_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.models import PluginFileEntry, PluginVersionContent

# Same fixed id as the migration that made the plugin tables.
ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")
ORGANIZATION_LIBRARY_NAME = "Organization library"
USER_UPLOADS_NAME = "My uploads"
PLUGIN_NAME_MAX_LENGTH = 64

_PLUGIN_NAME_INDEX = "uq_plugin_marketplace_name"

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


def add_plugin_version__no_commit(
    *,
    plugin: Plugin,
    content: PluginVersionContent,
    base_version_id: UUID | None,
    created_by: User | None,
    skip_if_unchanged: bool,
    db_session: Session,
    previous_manifest: Callable[[], list[PluginFileEntry]] | None = None,
) -> PluginVersion | None:
    """Add the next version of a plugin locked with ``lock_plugin`` and move its
    pointers. Returns None, and writes nothing, when ``skip_if_unchanged`` is
    set and the files equal the current version's files.

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
    return version


def get_version_ids_for_bundles(
    plugin_bundles: Mapping[UUID, str | None], db_session: Session
) -> dict[UUID, UUID]:
    """For each plugin id, the newest version that holds the given bundle.

    A response that shows a skill's files from its legacy bundle returns this
    id as the edit base. The id then always matches the files shown, also when
    a save commits between the two reads; that save makes the base stale."""
    pairs = {
        (plugin_id, bundle_file_id)
        for plugin_id, bundle_file_id in plugin_bundles.items()
        if bundle_file_id is not None
    }
    if not pairs:
        return {}
    rows = db_session.execute(
        select(PluginVersion.plugin_id, PluginVersion.id)
        .where(tuple_(PluginVersion.plugin_id, PluginVersion.bundle_file_id).in_(pairs))
        .order_by(PluginVersion.version_number)
    ).tuples()
    # Ordered by version number, so the newest version is written last.
    return dict(rows.all())


def delete_plugin__no_commit(plugin_id: UUID, db_session: Session) -> None:
    """Delete a plugin with its versions, skills, shares and choices. Bundle
    blobs are left for the cleanup task."""
    db_session.execute(delete(Plugin).where(Plugin.id == plugin_id))


def delete_user_upload_plugins__no_commit(db_session: Session, user_id: UUID) -> None:
    """Delete the plugins in the user's "My uploads" before a user delete.

    Until reads move to the plugin tables, the legacy skill rows are the source
    of truth and the user-delete guard checks only them. A plugin copied there
    can outlive its skill (delete, transfer, publish) and would block the
    marketplace cascade. The re-sync migrations rebuild any plugin that a live
    skill still needs.
    """
    db_session.execute(
        delete(Plugin).where(
            Plugin.marketplace_id.in_(
                select(Marketplace.id).where(
                    Marketplace.kind == MarketplaceKind.USER_UPLOADS,
                    Marketplace.owner_user_id == user_id,
                )
            )
        )
    )


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
