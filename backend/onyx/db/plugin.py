"""DB operations for plugins, their versions and marketplaces.

A version never changes. Each change to a plugin's files adds a version and
moves ``plugin.current_version_id``. In phase 1 a change to a plugin in the
Organization library also moves ``published_version_id``, so an edit reaches
the organization at once, as before plugins.

Access is on the plugin: shares, the install setting, the user choice and
publishing. Until the legacy skill tables are dropped, each access write to a
custom skill also goes here, in the same transaction. The helpers below each
mirror one legacy write.

Published means: in the Organization library. Publishing is one-way.

Lock order: a caller that also writes the legacy skill row locks that row
first, then these functions lock the plugin row. Many plugins are locked in id
order.

Functions here flush and never commit.
"""

import hashlib
from collections.abc import Callable, Iterable, Mapping
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MarketplaceKind,
    PluginInstallationPolicy,
    PluginKind,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
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
from onyx.db.utils import is_unique_violation
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
ACCOUNT_UPLOADS_NAME = "My uploads"
PLUGIN_NAME_MAX_LENGTH = 64

_PLUGIN_NAME_INDEX = "uq_plugin_marketplace_name"
_PLUGIN_PRIMARY_KEY = "plugin_pkey"

NameClashAction = Literal["raise", "rename"]


def account_uploads_marketplace_id(user_id: UUID) -> UUID:
    """Same id as SQL md5('account_uploads:' || user_id)::uuid."""
    digest = hashlib.md5(
        f"account_uploads:{user_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return UUID(digest)


def get_or_create_account_uploads__no_commit(
    user_id: UUID, db_session: Session
) -> UUID:
    """Return the user's "My uploads" id. Two first uploads at the same time
    both work: the second insert waits for the first and then does nothing."""
    db_session.execute(
        insert(Marketplace)
        .values(
            id=account_uploads_marketplace_id(user_id),
            kind=MarketplaceKind.ACCOUNT_UPLOADS,
            name=ACCOUNT_UPLOADS_NAME,
            owner_user_id=user_id,
            default_installation_policy=PluginInstallationPolicy.AVAILABLE,
        )
        .on_conflict_do_nothing()
    )
    return db_session.scalars(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.ACCOUNT_UPLOADS,
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
            name=skill.name,
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
    kind: PluginKind,
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
    description = content.skills[0].description if content.skills else ""
    version_id = uuid4()
    try:
        with db_session.begin_nested():
            plugin = Plugin(
                id=plugin_id,
                name=free_plugin_name(marketplace_id, name, db_session),
                description=description,
                kind=kind,
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

    if plugin.kind == PluginKind.SKILL:
        current_names = sorted(
            db_session.scalars(
                select(PluginSkill.name).where(
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
    if plugin.kind == PluginKind.SKILL and content.skills:
        plugin.description = content.skills[0].description
    db_session.flush()
    return version


def get_current_version_ids(
    plugin_ids: Iterable[UUID], db_session: Session
) -> dict[UUID, UUID]:
    ids = set(plugin_ids)
    if not ids:
        return {}
    rows = db_session.execute(
        select(Plugin.id, Plugin.current_version_id).where(Plugin.id.in_(ids))
    ).tuples()
    return dict(rows.all())


def delete_plugin__no_commit(plugin_id: UUID, db_session: Session) -> None:
    """Delete a plugin with its versions, skills, shares and choices. Bundle
    blobs are left for the cleanup task."""
    db_session.execute(delete(Plugin).where(Plugin.id == plugin_id))


def delete_account_upload_plugins__no_commit(
    db_session: Session, user_id: UUID
) -> None:
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
                    Marketplace.kind == MarketplaceKind.ACCOUNT_UPLOADS,
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
                name=skill.name,
                description=skill.description,
                skill_md=None,
                frontmatter=None,
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
        marketplace_id = get_or_create_account_uploads__no_commit(
            author_user_id, db_session
        )
    return create_plugin__no_commit(
        plugin_id=skill.id,
        name=skill.name,
        kind=PluginKind.SKILL,
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
    """The name a plugin asks for in a marketplace: for a plugin of kind skill,
    its skill name, which a "-2" suffix in the old marketplace does not change."""
    if plugin.kind == PluginKind.SKILL:
        skill_name = db_session.scalar(
            select(PluginSkill.name)
            .where(PluginSkill.plugin_version_id == plugin.current_version_id)
            .order_by(PluginSkill.path, PluginSkill.name)
            .limit(1)
        )
        if skill_name is not None:
            return skill_name
    return plugin.name


def _move_plugin__no_commit(
    *,
    plugin: Plugin,
    marketplace_id: UUID,
    on_name_clash: NameClashAction,
    clash_detail: Callable[[str], str],
    db_session: Session,
) -> None:
    name = _preferred_name(plugin, db_session)
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
    except IntegrityError as exc:
        if not is_unique_violation(exc, _PLUGIN_NAME_INDEX):
            raise
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
            marketplace_id=get_or_create_account_uploads__no_commit(
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


def set_plugin_user_share__no_commit(
    plugin_id: UUID,
    user_id: UUID,
    permission: SkillSharePermission | None,
    db_session: Session,
) -> None:
    """Mirror of one legacy user share. None removes it."""
    if permission is None:
        db_session.execute(
            delete(Plugin__User).where(
                Plugin__User.plugin_id == plugin_id, Plugin__User.user_id == user_id
            )
        )
        return
    stmt = insert(Plugin__User).values(
        plugin_id=plugin_id, user_id=user_id, permission=permission
    )
    db_session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Plugin__User.plugin_id, Plugin__User.user_id],
            set_={"permission": stmt.excluded.permission},
        )
    )


def replace_plugin_group_shares__no_commit(
    plugin_id: UUID,
    shares: Mapping[int, SkillSharePermission],
    db_session: Session,
) -> None:
    """Mirror of the legacy group shares. A kept share keeps its created_at."""
    db_session.execute(
        delete(Plugin__UserGroup).where(
            Plugin__UserGroup.plugin_id == plugin_id,
            Plugin__UserGroup.user_group_id.notin_(list(shares)),
        )
    )
    if not shares:
        return
    stmt = insert(Plugin__UserGroup).values(
        [
            {
                "plugin_id": plugin_id,
                "user_group_id": group_id,
                "permission": permission,
            }
            for group_id, permission in sorted(shares.items())
        ]
    )
    db_session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                Plugin__UserGroup.plugin_id,
                Plugin__UserGroup.user_group_id,
            ],
            set_={"permission": stmt.excluded.permission},
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
