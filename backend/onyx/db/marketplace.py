"""Apply a complete read using staged bundles; the caller owns commit and cleanup."""

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from onyx.db.marketplace_access import materialize_marketplace_access__no_commit
from onyx.db.models import Marketplace, Skill, SkillVersion, UserSkillPreference
from onyx.db.resource_version import prune_resource_bundles, write_resource_version
from onyx.db.skill import affected_user_ids_for_skills
from onyx.db.skill_version import SkillVersionAdapter
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.ingest import IngestedBundle
from onyx.skills.marketplace.models import ReconciliationResult
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
        # G3's manual name checks must use this same tenant/library lock.
        library = str(marketplace.owner_user_id or "company")
        db_session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(
                        func.current_schema() + ":skill-library:" + library, 0
                    )
                )
            )
        )
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
        if len(missing) > 5 and len(missing) * 2 > len(live):
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
        library_owner = case(
            (Skill.marketplace_id.is_not(None), Marketplace.owner_user_id),
            (Skill.public_permission.is_not(None), None),
            else_=Skill.author_user_id,
        )
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
