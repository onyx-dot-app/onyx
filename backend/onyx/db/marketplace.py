"""Apply a complete read using staged bundles; the caller owns commit and cleanup."""

from collections.abc import Collection, Mapping
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.enums import Permission
from onyx.db.marketplace_access import materialize_marketplace_access__no_commit
from onyx.db.marketplace_sync import request_marketplace_sync__no_commit
from onyx.db.models import Marketplace, Skill, SkillVersion, User, UserSkillPreference
from onyx.db.resource_access import lock_resource_access_user
from onyx.db.resource_version import prune_resource_bundles, write_resource_version
from onyx.db.skill import affected_user_ids_for_skills
from onyx.db.skill_library import lock_skill_library_names, skill_library_owner
from onyx.db.skill_version import SkillVersionAdapter
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.ingest import IngestedBundle
from onyx.skills.marketplace.models import (
    MarketplaceRetirementProposal,
    MarketplaceSyncStatus,
    ReconciliationResult,
)
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    CompleteMarketplace,
    FailedMarketplace,
    ReadySkill,
    UnsupportedPlugin,
)


def fetch_marketplace_sync_state(
    marketplace_id: UUID, db_session: Session
) -> tuple[Marketplace, dict[str, SkillVersion | None]]:
    """Internal sync snapshot; close the read session before storage/provider I/O."""
    marketplace = db_session.get(Marketplace, marketplace_id)
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
    current = {
        skill.marketplace_entry_key: skill.current_version
        for skill in db_session.scalars(
            select(Skill).where(
                Skill.marketplace_id == marketplace_id, Skill.retired_at.is_(None)
            )
        )
        if skill.marketplace_entry_key is not None
    }
    db_session.expunge_all()
    return marketplace, current


def confirm_marketplace_retirement__no_commit(
    marketplace_id: UUID,
    *,
    expected_revision: str,
    expected_skill_ids: Collection[UUID],
    user: User,
    db_session: Session,
) -> None:
    """Approve only the locked proposal using the authenticated actor's current rights.

    Persist approval and sync intent together. The caller dispatches after commit.
    This helper neither commits nor performs provider or storage I/O.
    """
    actor = lock_resource_access_user(user.id, db_session)
    marketplace = db_session.scalar(
        select(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if marketplace is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
    if marketplace.owner_user_id != actor.id and not has_global_permission(
        actor, Permission.MANAGE_SKILLS
    ):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    proposal = marketplace.retirement_proposal
    if (
        proposal is None
        or proposal.revision != expected_revision
        or proposal.skill_ids != tuple(sorted(expected_skill_ids))
    ):
        raise OnyxError(OnyxErrorCode.CONFLICT, "Retirement proposal has changed")
    if marketplace.sync_status != MarketplaceSyncStatus.NEEDS_CONFIRMATION:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Sync the marketplace again before confirming retirement",
        )
    marketplace.retirement_proposal = proposal.model_copy(update={"approved": True})
    db_session.flush()
    request_marketplace_sync__no_commit(marketplace_id, db_session)


def reconcile_marketplace__no_commit(
    marketplace_id: UUID,
    read: CompleteMarketplace | FailedMarketplace,
    *,
    revision: str,
    staged: Mapping[str, IngestedBundle],
    db_session: Session,
    created_by_user_id: UUID | None = None,
    recovery_keys: frozenset[str] = frozenset(),
) -> ReconciliationResult:
    """Stage changed/new ready entries before calling. Unchanged entries need no upload.

    recovery_keys forces fresh versions for unavailable current bundles, even
    with equal digests. Each ready recovery entry needs a fresh staged bundle.
    No storage or provider I/O occurs here. On success, commit before passing
    cleanup_file_ids to delete_unreferenced_skill_bundles. Before a commit attempt,
    clean staged files on failure. After an attempt, defer to the orphan sweep.
    A savepoint rolls back this application if the caller catches an exception.
    """
    cleanup = {bundle.bundle_file_id for bundle in staged.values()}
    if isinstance(read, FailedMarketplace):
        return ReconciliationResult(
            status="failed", reason=read.reason, cleanup_file_ids=cleanup
        )
    ready = {
        entry.entry_key: entry
        for entry in read.entries
        if isinstance(entry, ReadySkill)
    }
    if len({entry.entry_key for entry in read.entries}) != len(read.entries):
        raise ValueError("Duplicate marketplace entry key")
    for key, bundle in staged.items():
        entry = ready.get(key)
        if (
            entry is None
            or bundle.metadata.content_digest != entry.content_digest
            or bundle.canonical_name != entry.path.rsplit("/", 1)[-1]
        ):
            raise ValueError(f"Staged bundle does not match marketplace entry: {key}")
    lock_group_membership(db_session)
    with db_session.begin_nested():
        marketplace = db_session.scalar(
            select(Marketplace)
            .where(Marketplace.id == marketplace_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if marketplace is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
        names_to_lock = set(
            db_session.scalars(
                select(Skill.name).where(
                    Skill.marketplace_id == marketplace_id, Skill.retired_at.is_(None)
                )
            )
        )
        names_to_lock.update(entry.path.rsplit("/", 1)[-1] for entry in ready.values())
        lock_skill_library_names(marketplace.owner_user_id, names_to_lock, db_session)
        live = {
            skill.marketplace_entry_key: skill
            for skill in db_session.scalars(
                select(Skill)
                .where(
                    Skill.marketplace_id == marketplace_id, Skill.retired_at.is_(None)
                )
                .order_by(Skill.id)
                .with_for_update(of=Skill)
                .execution_options(populate_existing=True)
            )
        }
        for skill in live.values():
            db_session.refresh(skill, ["current_version"])
        present = {entry.entry_key for entry in read.entries}
        unsupported = {
            entry.entry_key
            for entry in read.entries
            if isinstance(entry, UnsupportedPlugin)
        }
        missing = [
            skill
            for key, skill in live.items()
            if key not in present and (key or "").split("/", 1)[0] not in unsupported
        ]
        proposal = MarketplaceRetirementProposal(
            revision=revision, skill_ids=tuple(sorted(skill.id for skill in missing))
        )
        approved = proposal.model_copy(update={"approved": True})
        if (
            len(missing) > 5
            and len(missing) * 2 > len(live)
            and marketplace.retirement_proposal != approved
        ):
            marketplace.retirement_proposal = proposal
            marketplace.sync_status = MarketplaceSyncStatus.NEEDS_CONFIRMATION
            marketplace.last_error = "needs confirmation"
            db_session.flush()
            return ReconciliationResult(
                status="needs_confirmation",
                reason=marketplace.last_error,
                cleanup_file_ids=cleanup,
            )
        before = affected_user_ids_for_skills(
            [skill.id for skill in live.values()], db_session
        )
        now = datetime.now(timezone.utc)
        for skill in missing:
            skill.retired_at = now
        if missing:
            db_session.execute(
                update(UserSkillPreference)
                .where(
                    UserSkillPreference.skill_id.in_([skill.id for skill in missing])
                )
                .values(enabled=False)
            )
        db_session.flush()
        library_owner = skill_library_owner()
        names = set(
            db_session.scalars(
                select(Skill.name)
                .outerjoin(Marketplace, Skill.marketplace_id == Marketplace.id)
                .where(
                    Skill.retired_at.is_(None),
                    library_owner.is_not_distinct_from(marketplace.owner_user_id),
                )
            )
        )
        blocked = {
            entry.entry_key: entry.reason
            for entry in read.entries
            if not isinstance(entry, ReadySkill)
        }
        changed: list[UUID] = []
        for entry in read.entries:
            if isinstance(entry, BlockedSkill):
                skill = live.get(entry.entry_key)
                if skill is not None and skill.marketplace_path != entry.path:
                    skill.marketplace_path = entry.path
                    changed.append(skill.id)
        used: set[str] = set()
        for key, entry in ready.items():
            name = entry.path.rsplit("/", 1)[-1]
            skill = live.get(key)
            if skill is None and name in names:
                blocked[key] = "name taken"
                continue
            if skill is not None and skill.name != name:
                raise ValueError(f"Marketplace skill name cannot change: {key}")
            current = skill.current_version if skill is not None else None
            if (
                key not in recovery_keys
                and current is not None
                and current.content_digest == entry.content_digest
            ):
                if skill is not None and skill.marketplace_path != entry.path:
                    skill.marketplace_path = entry.path
                    changed.append(skill.id)
                continue
            bundle = staged.get(key)
            if bundle is None:
                raise ValueError(
                    f"Changed marketplace entry needs a staged bundle: {key}"
                )
            if skill is None:
                skill = Skill(
                    name=name,
                    description=bundle.description,
                    author_user_id=marketplace.owner_user_id,
                    marketplace_id=marketplace.id,
                    marketplace_entry_key=key,
                    bundle_file_id=bundle.bundle_file_id,
                )
                db_session.add(skill)
                db_session.flush()
                names.add(name)
            adapter = SkillVersionAdapter(skill)
            write_resource_version(
                adapter,
                bundle_file_id=bundle.bundle_file_id,
                bundle_sha256=bundle.bundle_sha256,
                is_valid=True,
                metadata=bundle.metadata,
                created_by_user_id=created_by_user_id,
                marketplace_revision=revision,
                db_session=db_session,
            )
            skill.description = bundle.description
            skill.marketplace_path = entry.path
            cleanup.update(prune_resource_bundles(adapter, db_session))
            used.add(bundle.bundle_file_id)
            changed.append(skill.id)
        access_changed = materialize_marketplace_access__no_commit(
            marketplace_id, db_session
        )
        affected_skills = (
            set(changed) | access_changed | {skill.id for skill in missing}
        )
        after = affected_user_ids_for_skills(affected_skills, db_session)
        affected = {
            user_id
            for skill_id in affected_skills
            for user_id in before.get(skill_id, set()) | after.get(skill_id, set())
        }
        marketplace.blocked_entries = blocked
        marketplace.retirement_proposal = None
        marketplace.last_error = None
        marketplace.last_synced_revision = revision
        marketplace.last_synced_at = now
        db_session.flush()
        return ReconciliationResult(
            status="applied",
            changed_skill_ids=sorted(set(changed) | access_changed),
            affected_user_ids=affected,
            retired_skill_ids=[skill.id for skill in missing],
            blocked_entries=blocked,
            cleanup_file_ids=cleanup - used,
        )
