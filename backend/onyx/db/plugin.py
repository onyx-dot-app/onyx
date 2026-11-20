"""DB operations for plugins, their versions and marketplaces.

A version never changes. Each change to a plugin's files adds a version and
moves ``plugin.current_version_id``. The organization keeps the version in
``published_version_id`` until a publish update moves it.

Access is on the plugin: shares, the install setting, the user choice and
publishing. ``apply_plugin_access_change__no_commit`` is the one write path
for shares, publishing and install settings, with one set of rules.

Published means: in the Organization library. Publishing is one-way.

Many plugins are locked in id order.

Functions here flush and never commit.
"""

import hashlib
from collections.abc import Callable, Collection, Iterable, Mapping
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, and_, delete, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.db.enums import (
    MarketplaceKind,
    Permission,
    PluginInstallationPolicy,
    PluginPublishingPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    Marketplace,
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
    PluginSkill,
    PluginVersion,
    User,
    UserPluginPreference,
)
from onyx.db.plugin_access import (
    affected_user_ids_for_plugins,
    holds_one_root_skill,
    plugin_editable_by_user,
    seen_by_organization,
    visible_plugin_ids,
)
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
from onyx.server.settings.store import load_settings
from onyx.skills.models import (
    PluginFileEntry,
    PluginManifest,
    PluginNeed,
    PluginVersionContent,
)

# Same fixed id as the migration that made the plugin tables.
ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")

_PLUGIN_NAME_INDEX = "uq_plugin_marketplace_name"

NameClashAction = Literal["raise", "rename"]
SkillKey = tuple[UUID, str]
_RENAME_ATTEMPTS = 3


def is_skill_version(skill_paths: Iterable[str]) -> bool:
    """A version is a skill when it holds exactly one skill, with SKILL.md at
    the bundle root; otherwise it is a plugin. No column stores the result,
    so a later version can change it."""
    return list(skill_paths) == [""]


def version_is_skill(version_id: UUID, db_session: Session) -> bool:
    return is_skill_version(
        db_session.scalars(
            select(PluginSkill.path).where(PluginSkill.plugin_version_id == version_id)
        )
    )


def get_or_create_user_uploads__no_commit(user_id: UUID, db_session: Session) -> UUID:
    """Return the user's "My uploads" id. Two first uploads at the same time
    both work: the second insert waits for the first and then does nothing."""
    db_session.execute(
        insert(Marketplace)
        .values(
            # Same id as SQL md5('user_uploads:' || user_id)::uuid.
            id=UUID(
                hashlib.md5(
                    f"user_uploads:{user_id}".encode(), usedforsecurity=False
                ).hexdigest()
            ),
            kind=MarketplaceKind.USER_UPLOADS,
            name="My uploads",
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


def get_user_uploads_id(user_id: UUID, db_session: Session) -> UUID | None:
    return db_session.scalar(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.USER_UPLOADS,
            Marketplace.owner_user_id == user_id,
        )
    )


def get_or_create_organization_library__no_commit(db_session: Session) -> UUID:
    db_session.execute(
        insert(Marketplace)
        .values(
            id=ORGANIZATION_LIBRARY_ID,
            kind=MarketplaceKind.ORGANIZATION_LIBRARY,
            name="Organization library",
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


def get_organization_library_default(db_session: Session) -> PluginInstallationPolicy:
    """The default install setting of the Organization library: the setting of
    each published plugin that has none of its own. AVAILABLE before the
    library exists."""
    policy = db_session.scalar(
        select(Marketplace.default_installation_policy).where(
            Marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY
        )
    )
    return policy or PluginInstallationPolicy.AVAILABLE


def set_organization_library_default__no_commit(
    policy: PluginInstallationPolicy, db_session: Session
) -> set[UUID]:
    """Set the Organization library default and return the users with a
    running sandbox who could see a plugin that follows it, before or after.
    REQUIRED is refused: one switch would force every published plugin on
    every user."""
    if policy == PluginInstallationPolicy.REQUIRED:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The Organization library default cannot be Required.",
        )
    library_id = get_or_create_organization_library__no_commit(db_session)
    library = db_session.scalars(
        select(Marketplace).where(Marketplace.id == library_id).with_for_update()
    ).one()
    affected_ids = list(
        db_session.scalars(
            select(Plugin.id).where(
                Plugin.marketplace_id == library_id,
                Plugin.installation_policy.is_(None),
            )
        )
    )
    before = affected_user_ids_for_plugins(affected_ids, db_session)
    library.default_installation_policy = policy
    db_session.flush()
    return before | affected_user_ids_for_plugins(affected_ids, db_session)


def free_plugin_name(
    marketplace_id: UUID,
    name: str,
    db_session: Session,
) -> str:
    """The name, or else the first of name-2, name-3, ... that no plugin in the
    marketplace uses. The base is cut so the result fits 64 characters. Same
    rule as the plugin tables migration."""
    candidate = name
    suffix = 1
    while (
        db_session.scalar(
            select(Plugin.id).where(
                Plugin.marketplace_id == marketplace_id,
                Plugin.name == candidate,
            )
        )
        is not None
    ):
        suffix += 1
        base = name[: 64 - 1 - len(str(suffix))]
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
        manifest=(
            content.manifest.model_dump(mode="json")
            if content.manifest is not None
            else None
        ),
        needs=(
            [need.model_dump(mode="json") for need in content.needs]
            if content.needs is not None
            else None
        ),
        created_by_user_id=created_by.id if created_by is not None else None,
        created_by_email=created_by.email if created_by is not None else None,
        source_tree_sha=content.source_tree_sha,
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


def check_base_version(plugin: Plugin, base_version_id: UUID | None) -> None:
    """Refuse with PLUGIN_VERSION_STALE when ``base_version_id``, the version
    an edit started from, is given and is not the current version."""
    if base_version_id is not None and base_version_id != plugin.current_version_id:
        raise OnyxError(
            OnyxErrorCode.PLUGIN_VERSION_STALE,
            "This skill changed since you opened it. Reload it to get the "
            "newest version, then make your change again.",
        )


def next_version_number(plugin_id: UUID, db_session: Session) -> int:
    return (
        db_session.scalar(
            select(func.max(PluginVersion.version_number)).where(
                PluginVersion.plugin_id == plugin_id
            )
        )
        or 0
    ) + 1


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
    current_version_id. Returns None, and writes nothing, when
    ``skip_if_unchanged`` is set and the files equal the current version's
    files.

    ``base_version_id`` is checked with ``check_base_version``.
    ``previous_manifest`` supplies the current files when the current version
    has no file list yet."""
    check_base_version(plugin, base_version_id)
    current = db_session.get(PluginVersion, plugin.current_version_id)
    if current is None:
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Plugin has no current version.")

    if version_is_skill(current.id, db_session):
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

    version = _add_version_rows(
        version_id=uuid4(),
        plugin_id=plugin.id,
        version_number=next_version_number(plugin.id, db_session),
        content=content,
        created_by=created_by,
        db_session=db_session,
    )
    plugin.current_version_id = version.id
    description = version_description(content)
    if description is not None:
        plugin.description = description
    db_session.flush()
    return version


def version_description(content: PluginVersionContent) -> str | None:
    if is_skill_version(skill.path for skill in content.skills):
        return content.skills[0].description
    if content.manifest is not None:
        return content.manifest.description or ""
    return None


def list_plugin_versions(
    plugin_id: UUID, db_session: Session
) -> list[tuple[PluginVersion, bool, bool, bool]]:
    """Every version of a plugin, newest first, with whether it is the
    current, the published and the pending version."""
    return [
        (version, bool(is_current), bool(is_published), bool(is_pending))
        for version, is_current, is_published, is_pending in db_session.execute(
            select(
                PluginVersion,
                PluginVersion.id == Plugin.current_version_id,
                PluginVersion.id == Plugin.published_version_id,
                PluginVersion.id == Plugin.pending_version_id,
            )
            .join(Plugin, Plugin.id == PluginVersion.plugin_id)
            .where(PluginVersion.plugin_id == plugin_id)
            .order_by(PluginVersion.version_number.desc())
        ).tuples()
    ]


def get_plugin_version(
    plugin_id: UUID, version_id: UUID, db_session: Session
) -> PluginVersion:
    """One version of the plugin. A version of another plugin is not found."""
    version = db_session.scalar(
        select(PluginVersion).where(
            PluginVersion.id == version_id, PluginVersion.plugin_id == plugin_id
        )
    )
    if version is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill version not found.")
    return version


class StoredVersionContent(BaseModel):
    """What the database holds of one version's content. ``file_manifest`` and
    ``skill_md`` are None for a version copied from a legacy skill row."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    bundle_file_id: str | None
    # Name and description in the frontmatter of the skill at the bundle root.
    name: str | None
    description: str | None
    file_manifest: list[PluginFileEntry] | None
    skill_md: str | None


def get_stored_version_content(
    version_id: UUID, db_session: Session
) -> StoredVersionContent:
    row = db_session.execute(
        select(
            PluginVersion.bundle_file_id,
            PluginSkill.frontmatter["name"].astext,
            PluginSkill.frontmatter["description"].astext,
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
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill version not found.")
    bundle_file_id, name, description, manifest, skill_md = row
    return StoredVersionContent(
        bundle_file_id=bundle_file_id,
        name=name,
        description=description,
        file_manifest=(
            [PluginFileEntry.model_validate(entry) for entry in manifest]
            if manifest is not None
            else None
        ),
        skill_md=skill_md,
    )


class StoredSkillMd(BaseModel):
    """The raw root SKILL.md of a version, None where the version stores no
    text (over 256 KiB or not yet repaired), and the bundle that holds it."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    bundle_file_id: str | None
    skill_md: str | None


def get_visible_versions_skill_md(
    skills: Collection[SkillKey], user_id: UUID, db_session: Session
) -> dict[SkillKey, StoredSkillMd]:
    rows = db_session.execute(
        select(
            PluginVersion.id,
            PluginSkill.path,
            PluginVersion.bundle_file_id,
            PluginSkill.skill_md,
        )
        .join(PluginSkill, PluginSkill.plugin_version_id == PluginVersion.id)
        .where(
            tuple_(PluginVersion.id, PluginSkill.path).in_(list(skills)),
            PluginVersion.plugin_id.in_(visible_plugin_ids(user_id)),
        )
    )
    return {
        (version_id, path): StoredSkillMd(
            bundle_file_id=bundle_file_id, skill_md=skill_md
        )
        for version_id, path, bundle_file_id, skill_md in rows
    }


def get_versions_needs(
    version_ids: Iterable[UUID], db_session: Session
) -> dict[UUID, list[PluginNeed]]:
    ids = sorted(set(version_ids))
    if not ids:
        return {}
    return {
        version_id: [PluginNeed.model_validate(need) for need in needs or ()]
        for version_id, needs in db_session.execute(
            select(PluginVersion.id, PluginVersion.needs).where(
                PluginVersion.id.in_(ids), PluginVersion.needs.is_not(None)
            )
        ).tuples()
    }


def get_version_manifest(
    version_id: UUID, db_session: Session
) -> PluginManifest | None:
    manifest = db_session.scalar(
        select(PluginVersion.manifest).where(PluginVersion.id == version_id)
    )
    return PluginManifest.model_validate(manifest) if manifest is not None else None


class VersionSkill(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    name: str
    description: str


def list_version_skills(version_id: UUID, db_session: Session) -> list[VersionSkill]:
    return [
        VersionSkill(path=path, name=name, description=description)
        for path, name, description in db_session.execute(
            select(
                PluginSkill.path,
                PluginSkill.frontmatter["name"].astext,
                PluginSkill.frontmatter["description"].astext,
            )
            .where(PluginSkill.plugin_version_id == version_id)
            .order_by(PluginSkill.path)
        ).tuples()
    ]


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


# --- Skill plugins and their access ----------------------------------------


def create_plugin__no_commit(
    plugin_id: UUID,
    name: str,
    content: PluginVersionContent,
    author: User,
    db_session: Session,
) -> Plugin:
    marketplace_id = get_or_create_user_uploads__no_commit(author.id, db_session)
    version_id = uuid4()
    try:
        with db_session.begin_nested():
            plugin = Plugin(
                id=plugin_id,
                name=free_plugin_name(marketplace_id, name, db_session),
                description=version_description(content) or "",
                marketplace_id=marketplace_id,
                author_user_id=author.id,
                current_version_id=version_id,
            )
            db_session.add(plugin)
            db_session.flush()
            _add_version_rows(
                version_id=version_id,
                plugin_id=plugin_id,
                version_number=1,
                content=content,
                created_by=author,
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


def create_synced_plugin__no_commit(
    marketplace: Marketplace,
    entry_key: str,
    content: PluginVersionContent,
    created_by: User | None,
    db_session: Session,
) -> Plugin:
    """Create the plugin of a marketplace entry. A personal marketplace's
    plugin belongs to its owner; a company one has no author and the
    organization runs its version."""
    if content.manifest is None:
        raise RuntimeError("Bug: a synced plugin has a manifest.")
    plugin_id = uuid4()
    version_id = uuid4()
    plugin = Plugin(
        id=plugin_id,
        name=free_plugin_name(marketplace.id, content.manifest.name, db_session),
        description=version_description(content) or "",
        marketplace_id=marketplace.id,
        author_user_id=marketplace.owner_user_id,
        current_version_id=version_id,
        published_version_id=version_id if marketplace.owner_user_id is None else None,
        marketplace_entry_key=entry_key,
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
    return plugin


def find_upload_target(name: str, user_id: UUID, db_session: Session) -> Plugin | None:
    return db_session.scalars(
        select(Plugin)
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .where(
            Plugin.name == name,
            or_(
                and_(
                    Marketplace.kind == MarketplaceKind.USER_UPLOADS,
                    Marketplace.owner_user_id == user_id,
                ),
                Marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY,
            ),
            plugin_editable_by_user(Plugin, user_id),
            ~holds_one_root_skill(Plugin.current_version_id.expression),
        )
        .order_by((Marketplace.kind != MarketplaceKind.USER_UPLOADS).asc(), Plugin.id)
        .limit(1)
    ).one_or_none()


def _move_plugin__no_commit(
    *,
    plugin: Plugin,
    marketplace_id: UUID,
    on_name_clash: NameClashAction,
    clash_detail: Callable[[str], str],
    db_session: Session,
) -> None:
    # A plugin whose current version is a skill asks for its skill name, which
    # a "-2" suffix in the old marketplace does not change.
    rows = db_session.execute(
        select(PluginSkill.path, PluginSkill.frontmatter["name"].astext).where(
            PluginSkill.plugin_version_id == plugin.current_version_id
        )
    ).all()
    preferred = (
        rows[0][1]
        if is_skill_version(path for path, _ in rows) and rows[0][1]
        else plugin.name
    )
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


def private_plugins_blocking_user_delete(user_id: UUID) -> Select[tuple[Plugin]]:
    """The plugins in the user's "My uploads". A user delete does not release
    them."""
    return (
        select(Plugin)
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .where(
            Marketplace.kind == MarketplaceKind.USER_UPLOADS,
            Marketplace.owner_user_id == user_id,
        )
        .order_by(Plugin.name, Plugin.id)
    )


def publish_plugin__no_commit(
    plugin_id: UUID,
    on_name_clash: NameClashAction,
    db_session: Session,
) -> None:
    """Publish a plugin to the organization: move it to the Organization library,
    set published_version_id to current_version_id and clear the pending
    request. Publishing is one-way. A plugin that is already in the
    Organization library does not change.

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
        clash_detail=lambda name: (
            f"The organization already has a published skill named '{name}'. "
            "Two published skills cannot use the same name."
        ),
        db_session=db_session,
    )
    plugin.published_version_id = plugin.current_version_id
    plugin.pending_version_id = None
    db_session.flush()


def publish_or_request_review__no_commit(
    plugin: Plugin,
    version_id: UUID,
    actor: User | None,
    on_name_clash: NameClashAction,
    db_session: Session,
) -> None:
    """Publish a version of a locked plugin, or make it the pending request
    (replacing any older one) when the Publishing setting requires review for
    ``actor``; OFF raises. The one place the setting applies. ``actor`` None
    is a system or approved publish and always publishes. An organization-wide
    plugin manager always publishes. A publish clears the pending request."""
    if actor is not None and not has_global_permission(
        actor, Permission.MANAGE_PLUGINS
    ):
        # A setting that cannot be read stops the publish.
        policy = load_settings(raise_on_error=True).plugin_publishing
        if policy == PluginPublishingPolicy.OFF:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Publishing to the organization is turned off. Ask an admin to "
                "publish this skill.",
            )
        if policy == PluginPublishingPolicy.REQUIRES_REVIEW:
            plugin.pending_version_id = version_id
            db_session.flush()
            return
    publish_plugin__no_commit(plugin.id, on_name_clash, db_session)
    plugin.published_version_id = version_id
    plugin.pending_version_id = None
    db_session.flush()


def transfer_plugin__no_commit(
    plugin_id: UUID,
    new_author_user_id: UUID,
    db_session: Session,
    on_name_clash: NameClashAction = "raise",
) -> None:
    """Set the plugin's author. A private plugin also moves to the new owner's
    "My uploads". On a name clash there, "raise" refuses with CONFLICT and
    "rename" takes the next free name. A published plugin stays in the
    Organization library."""
    plugin = lock_plugin(plugin_id, db_session)
    if plugin is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
    marketplace_kind = db_session.scalar(
        select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
    )
    if marketplace_kind != MarketplaceKind.ORGANIZATION_LIBRARY:
        _move_plugin__no_commit(
            plugin=plugin,
            marketplace_id=get_or_create_user_uploads__no_commit(
                new_author_user_id, db_session
            ),
            on_name_clash=on_name_clash,
            clash_detail=lambda name: (
                f"The new owner already has a skill named '{name}'. "
                "Ask them to delete or rename it first."
            ),
            db_session=db_session,
        )
    plugin.author_user_id = new_author_user_id
    db_session.flush()


class PluginGroupRow(BaseModel):
    """The state of one plugin__user_group row. No permission: the row holds
    only a group install setting and grants no access."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    permission: SkillSharePermission | None
    installation_policy: PluginInstallationPolicy | None


def set_plugin_preferences__no_commit(
    user_id: UUID,
    plugin_ids: Iterable[UUID],
    enabled: bool,
    db_session: Session,
) -> None:
    """Write the user's on/off choice. enabled_at is set each time the user
    turns a plugin on."""
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


# --- Access changes ----------------------------------------------------------


class PluginAccessMode(str, Enum):
    """REPLACE: the supplied grants are the new set. ADD_ONLY: the supplied
    grants are added to the current ones or change their level; no grant is
    removed."""

    REPLACE = "replace"
    ADD_ONLY = "add_only"


class PluginUserGrant(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    user_id: UUID
    permission: SkillSharePermission


class PluginGroupGrant(BaseModel):
    """A group share. The group keeps its install setting."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    group_id: int
    permission: SkillSharePermission


class PluginGroupSetting(BaseModel):
    """A group install setting with no change to the group's share. A group
    with no row gets a setting-only row. None removes the setting, and a row
    with no permission is then deleted."""

    model_config = ConfigDict(frozen=True)

    group_id: int
    installation_policy: PluginInstallationPolicy | None


class PluginAccessChange(BaseModel):
    """One access change for one or more plugins. A field at its default does
    not change anything.

    ``company_installation_policy``: UNSET keeps it, None means "use the
    marketplace default", and a value sets that value. ``group_settings`` apply
    after ``group_grants``. ``on_name_clash`` applies when ``publish`` moves a
    plugin to the Organization library."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    user_grants: tuple[PluginUserGrant, ...] | None = None
    group_grants: tuple[PluginGroupGrant, ...] | None = None
    group_settings: tuple[PluginGroupSetting, ...] | None = None
    publish: bool = False
    on_name_clash: NameClashAction = "raise"
    company_installation_policy: PluginInstallationPolicy | None | UnsetType = UNSET
    mode: PluginAccessMode = PluginAccessMode.REPLACE


class PluginAccessResult(BaseModel):
    """``affected_user_ids``: users with a running sandbox who could see one
    of the plugins before or after the change. ``failures``: plugins whose
    change was refused or failed and rolled back."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    affected_user_ids: set[UUID]
    failures: dict[UUID, OnyxError]

    def raise_first_failure(self) -> None:
        for plugin_id in sorted(self.failures):
            raise self.failures[plugin_id]


class AccessRows(BaseModel):
    """The grants of one plugin or one integration, now and after a change."""

    model_config = ConfigDict(strict=True, arbitrary_types_allowed=True)

    # For an integration: its company setting is above NOT_AVAILABLE.
    published: bool
    user_grants: dict[UUID, SkillSharePermission]
    group_rows: dict[int, PluginGroupRow]
    # The grants and rows after the change; None when they do not change.
    new_user_grants: dict[UUID, SkillSharePermission] | None = None
    new_group_rows: dict[int, PluginGroupRow] | None = None


class _LockedPlugin(AccessRows):
    plugin: Plugin


def _lock_for_access_change(
    ids: list[UUID], change: PluginAccessChange, db_session: Session
) -> tuple[dict[UUID, _LockedPlugin], dict[UUID, OnyxError]]:
    """Lock the plugins in id order, and read their current grants and the
    grants after ``change``."""
    plugins: dict[UUID, Plugin] = {}
    missing: dict[UUID, OnyxError] = {}
    for plugin_id in ids:
        plugin = lock_plugin(plugin_id, db_session)
        if plugin is None:
            missing[plugin_id] = OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
        else:
            plugins[plugin_id] = plugin
    found = list(plugins)
    published = set(
        db_session.scalars(
            select(Plugin.id)
            .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
            .where(Plugin.id.in_(found), seen_by_organization(Marketplace))
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
    locked = {
        plugin_id: _LockedPlugin(
            plugin=plugin,
            published=plugin_id in published,
            user_grants=user_grants.get(plugin_id, {}),
            group_rows=group_rows.get(plugin_id, {}),
        )
        for plugin_id, plugin in plugins.items()
    }
    for item in locked.values():
        item.new_user_grants = _new_user_grants(item, change)
        item.new_group_rows = new_group_rows(item.group_rows, change)
    return locked, missing


def _new_user_grants(
    locked: _LockedPlugin, change: PluginAccessChange
) -> dict[UUID, SkillSharePermission] | None:
    """The user grants after the change, or None when they do not change. The
    author never has a grant."""
    if change.user_grants is None:
        return None
    requested = {grant.user_id: grant.permission for grant in change.user_grants}
    return {
        user_id: permission
        for user_id, permission in (
            requested
            if change.mode == PluginAccessMode.REPLACE
            else locked.user_grants | requested
        ).items()
        if user_id != locked.plugin.author_user_id
    }


def new_group_rows(
    current_rows: Mapping[int, PluginGroupRow], change: PluginAccessChange
) -> dict[int, PluginGroupRow] | None:
    """The group rows after the change, or None when they do not change. A
    group keeps its install setting unless a group setting sets one. On
    REPLACE, a group left out of the grants loses its permission but keeps its
    row if it has a setting. A row with neither is deleted."""
    if change.group_grants is None and change.group_settings is None:
        return None
    rows: dict[int, PluginGroupRow] = {}
    if change.group_grants is None:
        rows = dict(current_rows)
    else:
        for group_id, row in current_rows.items():
            if change.mode == PluginAccessMode.ADD_ONLY:
                rows[group_id] = row
            elif row.installation_policy is not None:
                rows[group_id] = PluginGroupRow(
                    permission=None, installation_policy=row.installation_policy
                )
        for grant in change.group_grants:
            current = current_rows.get(grant.group_id)
            rows[grant.group_id] = PluginGroupRow(
                permission=grant.permission,
                installation_policy=(
                    current.installation_policy if current is not None else None
                ),
            )
    for setting in change.group_settings or ():
        current = rows.get(setting.group_id)
        rows[setting.group_id] = PluginGroupRow(
            permission=current.permission if current is not None else None,
            installation_policy=setting.installation_policy,
        )
    return {
        group_id: row
        for group_id, row in rows.items()
        if row.permission is not None or row.installation_policy is not None
    }


def _group_shares(
    rows: Mapping[int, PluginGroupRow],
) -> dict[int, SkillSharePermission]:
    return {
        group_id: row.permission
        for group_id, row in rows.items()
        if row.permission is not None
    }


def check_access_change(
    items: Collection[AccessRows],
    change: PluginAccessChange,
    actor: User | None,
    db_session: Session,
    manage_permission: Permission = Permission.MANAGE_PLUGINS,
) -> None:
    """The checks that apply to the whole set of plugins or integrations.
    They raise before any write. ``manage_permission`` is MANAGE_ACTIONS for
    integrations."""
    is_global_manager = actor is not None and has_global_permission(
        actor, manage_permission
    )
    subject, manager, a_manager = (
        ("integration", "action manager", "an action manager")
        if manage_permission is Permission.MANAGE_ACTIONS
        else ("skill", "skill manager", "a skill manager")
    )
    if actor is not None and not is_global_manager:
        if is_set(change.company_installation_policy):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                f"Only an organization-wide {manager} can change the install setting.",
            )
        if change.group_settings is not None:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                f"Only an organization-wide {manager} can set a group install setting.",
            )
        # With the admin Sharing setting off, only an organization-wide manager
        # adds a share or changes its level. Removing a share stays allowed.
        adds_share = any(
            locked.user_grants.get(user_id) != permission
            for locked in items
            for user_id, permission in (locked.new_user_grants or {}).items()
        ) or any(
            _group_shares(locked.group_rows).get(group_id) != permission
            for locked in items
            for group_id, permission in _group_shares(
                locked.new_group_rows or {}
            ).items()
        )
        if adds_share:
            check_sharing_allowed(subject)
    if change.group_grants is None and change.group_settings is None:
        return
    requested_group_ids = sorted(
        {grant.group_id for grant in change.group_grants or ()}
    )
    setting_group_ids = sorted(
        {setting.group_id for setting in change.group_settings or ()}
    )
    assert_not_shared_with_default_group(
        db_session, sorted(set(requested_group_ids) | set(setting_group_ids))
    )
    for locked in items:
        for group_id, row in (locked.new_group_rows or {}).items():
            if (
                row.permission is None
                or row.installation_policy != PluginInstallationPolicy.NOT_AVAILABLE
            ):
                continue
            current = locked.group_rows.get(group_id)
            if current is not None and current.permission is not None:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "A group with a share cannot be Not available. Remove the "
                    "group's share first.",
                )
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"This {subject} is Not available to one of the groups. Ask "
                f"{a_manager} to change that group's access before you share "
                "with it.",
            )

    # A change to group shares is a ``manage_permission`` action. The
    # current shares come from the database, never the request, so a
    # reassignment cannot escape scope. Re-sending the current set is no change.
    changed = [
        locked
        for locked in items
        if _group_shares(locked.new_group_rows or {})
        != _group_shares(locked.group_rows)
    ]
    if actor is None or not changed:
        return
    assert_within_scope(
        actor,
        db_session,
        permission=manage_permission,
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


def check_sharing_allowed(subject: str = "skill") -> None:
    """With the admin Sharing setting off, refuse a new share by someone who is
    not an organization-wide manager. The caller checks the actor."""
    if not load_settings(raise_on_error=True).plugin_sharing:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Sharing with people and groups is turned off. Ask an admin to "
            f"share this {subject}.",
        )


def _write_user_grants__no_commit(locked: _LockedPlugin, db_session: Session) -> None:
    """Write the user grants after the change, unless they do not change. A
    kept share keeps its created_at."""
    grants = locked.new_user_grants
    if grants is None:
        return
    plugin_id = locked.plugin.id
    try:
        with db_session.begin_nested():
            db_session.execute(
                delete(Plugin__User).where(
                    Plugin__User.plugin_id == plugin_id,
                    Plugin__User.user_id.notin_(list(grants)),
                )
            )
            if grants:
                stmt = insert(Plugin__User).values(
                    [
                        {
                            "plugin_id": plugin_id,
                            "user_id": user_id,
                            "permission": permission,
                        }
                        for user_id, permission in sorted(grants.items())
                    ]
                )
                db_session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[Plugin__User.plugin_id, Plugin__User.user_id],
                        set_={"permission": stmt.excluded.permission},
                    )
                )
    except IntegrityError as exc:
        if is_fk_violation(exc):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "One or more user share targets do not exist.",
            ) from exc
        raise


def _write_group_rows__no_commit(
    locked: _LockedPlugin,
    rows: Mapping[int, PluginGroupRow],
    db_session: Session,
) -> None:
    """Make the plugin's group rows equal ``rows``. A kept row keeps its
    created_at."""
    plugin_id = locked.plugin.id
    try:
        with db_session.begin_nested():
            db_session.execute(
                delete(Plugin__UserGroup).where(
                    Plugin__UserGroup.plugin_id == plugin_id,
                    Plugin__UserGroup.user_group_id.notin_(list(rows)),
                )
            )
            if rows:
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
    except IntegrityError as exc:
        if is_fk_violation(exc):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "One or more group share targets do not exist.",
            ) from exc
        raise


def _apply_to_plugin__no_commit(
    locked: _LockedPlugin,
    change: PluginAccessChange,
    actor: User | None,
    db_session: Session,
) -> None:
    plugin = locked.plugin
    if change.publish:
        if (
            actor is not None
            and plugin.author_user_id != actor.id
            and not has_global_permission(actor, Permission.MANAGE_PLUGINS)
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "You do not have permission to change organization-wide skill access.",
            )
        if plugin.published_version_id is None:
            publish_or_request_review__no_commit(
                plugin,
                plugin.current_version_id,
                actor,
                change.on_name_clash,
                db_session,
            )

    if is_set(change.company_installation_policy):
        plugin.installation_policy = change.company_installation_policy
        db_session.flush()

    _write_user_grants__no_commit(locked, db_session)
    if locked.new_group_rows is not None:
        _write_group_rows__no_commit(locked, locked.new_group_rows, db_session)


def apply_plugin_access_change__no_commit(
    plugin_ids: Iterable[UUID],
    change: PluginAccessChange,
    actor: User | None,
    db_session: Session,
) -> PluginAccessResult:
    """The one write path for shares, publishing and install settings.

    Locks the plugins in id order. Checks the rules once for the set and
    raises before any write when one fails. Then writes each plugin in its own
    savepoint: a refusal or failure on one plugin rolls back that plugin only and lands in
    ``failures``. The affected users are read for the whole set before and
    after the writes. The caller commits, then pushes once.

    Rules: a company install setting needs organization-wide MANAGE_PLUGINS. A
    group install setting (``group_settings``) needs organization-wide
    MANAGE_PLUGINS too. A group row with a permission cannot be
    NOT_AVAILABLE. A change
    to group shares must stay within the actor's managed scope. With the admin
    Sharing setting off, only organization-wide MANAGE_PLUGINS adds shares.
    Publishing needs the author or organization-wide MANAGE_PLUGINS.

    ``actor`` None is a system write that the caller authorized, such as an
    ownership transfer. The permission checks are skipped; the other rules
    still apply."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return PluginAccessResult(affected_user_ids=set(), failures={})
    plugins, failures = _lock_for_access_change(ids, change, db_session)
    check_access_change(plugins.values(), change, actor, db_session)

    before = affected_user_ids_for_plugins(plugins, db_session)
    for plugin_id, locked in plugins.items():
        try:
            with db_session.begin_nested():
                _apply_to_plugin__no_commit(locked, change, actor, db_session)
        except OnyxError as exc:
            failures[plugin_id] = exc
    after = affected_user_ids_for_plugins(plugins, db_session)
    return PluginAccessResult(affected_user_ids=before | after, failures=failures)
