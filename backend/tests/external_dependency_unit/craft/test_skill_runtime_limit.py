"""The run-time skill limit (G7b): every plugin that fits in 900 MB and
10,000 files, in the keep order.

Sizes are written to plugin_version rows (manifest, size, file count), so
small real bundles stand for large ones. Earlier tests leave plugins in the
organization library, so each test measures the room its user has first."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import (
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import Plugin, PluginVersion, Skill, User, UserPluginPreference
from onyx.db.plugin import set_plugin_preferences__no_commit
from onyx.db.plugin_access import load_user_plugin_states
from onyx.db.skill import (
    SkillSharingChange,
    create_custom_skill__no_commit,
    list_runtime_skills_for_user,
    replace_skill_bundle,
    replace_skill_shares,
)
from onyx.db.skill_limit import users_past_write_limit
from onyx.file_store.file_store import get_default_file_store
from onyx.skills import push
from onyx.skills.ingest import delete_bundle_blob, ingest_skill_bundle
from onyx.skills.limits import SKILL_RUNTIME_MAX_BYTES, SKILL_RUNTIME_MAX_FILES
from onyx.skills.models import SkillUsage, UserPastWriteLimit
from onyx.skills.push import UserSkillsPayload
from tests.external_dependency_unit.craft.db_helpers import (
    make_sandbox,
    make_skillless_plugin,
    make_user,
    share_plugin_with_user,
)

_MB = 1024 * 1024


@pytest.fixture
def resized(db_session: Session) -> Iterator[list[UUID]]:
    """Plugins whose sizes or settings a test changed. Afterwards they are
    hidden and small again, so they do not count for later tests."""
    plugin_ids: list[UUID] = []
    yield plugin_ids
    db_session.rollback()
    if not plugin_ids:
        return
    db_session.execute(
        update(PluginVersion)
        .where(PluginVersion.plugin_id.in_(plugin_ids))
        .values(file_manifest=None, unpacked_size_bytes=0, file_count=0)
    )
    db_session.execute(
        update(Plugin)
        .where(Plugin.id.in_(plugin_ids))
        .values(installation_policy=PluginInstallationPolicy.NOT_AVAILABLE)
    )
    db_session.commit()


def _set_files(
    db_session: Session,
    plugin_id: UUID,
    sizes: list[int],
    resized: list[UUID],
    version_id: UUID | None = None,
) -> None:
    """Give a version (default: the current one) these file sizes."""
    if version_id is None:
        version_id = db_session.scalar(
            select(Plugin.current_version_id).where(Plugin.id == plugin_id)
        )
    db_session.execute(
        update(PluginVersion)
        .where(PluginVersion.id == version_id)
        .values(
            file_manifest=[
                {"path": f"f{index}", "size": size, "sha256": "0" * 64}
                for index, size in enumerate(sizes)
            ],
            unpacked_size_bytes=sum(sizes),
            file_count=len(sizes),
        )
    )
    db_session.flush()
    resized.append(plugin_id)


def _set_policy(
    db_session: Session,
    plugin_id: UUID,
    policy: PluginInstallationPolicy,
    created_at: datetime | None = None,
) -> None:
    values: dict[str, Any] = {"installation_policy": policy}
    if created_at is not None:
        values["created_at"] = created_at
    db_session.execute(update(Plugin).where(Plugin.id == plugin_id).values(**values))
    db_session.flush()


def _turn_on(
    db_session: Session, user: User, plugin_id: UUID, enabled_at: datetime | None
) -> None:
    set_plugin_preferences__no_commit(user.id, [plugin_id], True, db_session)
    db_session.execute(
        update(UserPluginPreference)
        .where(
            UserPluginPreference.user_id == user.id,
            UserPluginPreference.plugin_id == plugin_id,
        )
        .values(enabled_at=enabled_at)
    )
    db_session.flush()


def _free_room(db_session: Session, user: User) -> SkillUsage:
    """Run-time room left for plugins that sort before the plugins earlier
    tests left as Installed by default."""
    built_in_names = {
        skill.name
        for skill in list_runtime_skills_for_user(user=user, db_session=db_session)
        if skill.version is None
    }
    built_in_files = [
        content
        for path, content in push.build_user_skills_payload(
            user, db_session
        ).files.items()
        if path.partition("/")[0] in built_in_names
    ]
    used = SkillUsage(
        bytes=sum(len(content) for content in built_in_files),
        files=len(built_in_files),
    )
    for state in load_user_plugin_states([user.id], db_session, runnable_only=True):
        if (
            state.installation_policy == PluginInstallationPolicy.REQUIRED
            or state.turned_on
        ):
            used += state.usage or SkillUsage()
    return SkillUsage(
        bytes=SKILL_RUNTIME_MAX_BYTES - used.bytes,
        files=SKILL_RUNTIME_MAX_FILES - used.files,
    )


def _omitted(payload: UserSkillsPayload) -> set[UUID]:
    return {omission.plugin_id for omission in payload.omissions}


def _at(day: int) -> datetime:
    return datetime(2099, 1, day, tzinfo=timezone.utc)


def test_keep_order_when_not_every_plugin_fits(
    db_session: Session,
    seeded_skill: Callable[..., Skill],
    resized: list[UUID],
) -> None:
    """Required, then turned on (newest first, an Installed by default plugin
    turned on again counts), then Installed by default by plugin.created_at,
    a tie broken by plugin.id."""
    user = make_user(db_session, standard_account=True)
    db_session.commit()
    room = _free_room(db_session, user).bytes
    tag = user.id.hex[:8]

    def plugin(name: str, share: int) -> Skill:
        skill = seeded_skill(f"rt-{name}-{tag}", public=True)
        _set_files(db_session, skill.id, [room * share // 100], resized)
        return skill

    required = plugin("required", 30)
    _set_policy(db_session, required.id, PluginInstallationPolicy.REQUIRED, _at(1))
    turned_on_again = plugin("again", 2)
    _set_policy(
        db_session,
        turned_on_again.id,
        PluginInstallationPolicy.DEFAULT,
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    _turn_on(db_session, user, turned_on_again.id, _at(4))
    newer_on = plugin("newer-on", 35)
    older_on = plugin("older-on", 35)
    for skill, day in ((newer_on, 3), (older_on, 2)):
        _set_policy(db_session, skill.id, PluginInstallationPolicy.AVAILABLE)
        _turn_on(db_session, user, skill.id, _at(day))
    newer_default = plugin("newer-default", 15)
    older_default = plugin("older-default", 15)
    _set_policy(db_session, newer_default.id, PluginInstallationPolicy.DEFAULT, _at(2))
    _set_policy(db_session, older_default.id, PluginInstallationPolicy.DEFAULT, _at(1))
    tie = [plugin("tie-a", 2), plugin("tie-b", 2)]
    for skill in tie:
        _set_policy(
            db_session,
            skill.id,
            PluginInstallationPolicy.DEFAULT,
            datetime(2098, 12, 31, tzinfo=timezone.utc),
        )
    first_tie, second_tie = sorted(tie, key=lambda skill: skill.id)
    db_session.commit()

    payload = push.build_user_skills_payload(user, db_session)

    # 30 + 2 + 35 fit; the older turned-on 35 does not. Then 15 + 15 + 2.
    mine = {
        required.id,
        turned_on_again.id,
        newer_on.id,
        older_on.id,
        newer_default.id,
        older_default.id,
        first_tie.id,
        second_tie.id,
    }
    assert _omitted(payload) & mine == {older_on.id, second_tie.id}
    for skill in (required, turned_on_again, newer_on, newer_default, first_tie):
        assert f"{skill.name}/SKILL.md" in payload.files
    for omission in payload.omissions:
        if omission.plugin_id == older_on.id:
            assert omission.name == older_on.name
            assert omission.reason == "bytes"
            assert omission.bytes == room * 35 // 100


def test_a_turned_on_choice_with_no_enabled_at_sorts_by_its_share_time(
    db_session: Session,
    seeded_skill: Callable[..., Skill],
) -> None:
    user = make_user(db_session, standard_account=True)
    tag = user.id.hex[:8]
    backfilled = seeded_skill(f"rt-backfilled-{tag}", public=True)
    older = seeded_skill(f"rt-older-{tag}", public=True)
    _set_policy(db_session, backfilled.id, PluginInstallationPolicy.AVAILABLE, _at(5))
    _set_policy(db_session, older.id, PluginInstallationPolicy.AVAILABLE, _at(1))
    _turn_on(db_session, user, backfilled.id, None)
    _turn_on(db_session, user, older.id, _at(3))

    keys = {
        state.plugin_id: state.keep_key
        for state in load_user_plugin_states(
            [user.id], db_session, [backfilled.id, older.id]
        )
    }

    assert keys[backfilled.id] < keys[older.id]


def _versioned_bundle(name: str, version: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Skill {version}\n---\n\n{version}\n",
        )
        bundle_zip.writestr("notes.md", f"notes {version}")
    return output.getvalue()


def test_recipient_is_charged_the_current_version_and_org_user_the_published(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    resized: list[UUID],
) -> None:
    author = make_user(db_session, standard_account=True)
    recipient = make_user(db_session, standard_account=True)
    org_only = make_user(db_session, standard_account=True)
    name = f"rt-versioned-{author.id.hex[:8]}"
    file_store = get_default_file_store()
    first = ingest_skill_bundle(
        _versioned_bundle(name, "one"), f"{name}.zip", file_store, expected_name=name
    )
    second = ingest_skill_bundle(
        _versioned_bundle(name, "two"), f"{name}.zip", file_store, expected_name=name
    )
    try:
        skill, _ = create_custom_skill__no_commit(
            first,
            author,
            db_session,
            change=SkillSharingChange(
                public_permission=SkillSharePermission.VIEWER,
                set_public_permission=True,
            ),
        )
        published_version_id = db_session.scalar(
            select(Plugin.current_version_id).where(Plugin.id == skill.id)
        )
        replace_skill_shares(
            skill=skill,
            db_session=db_session,
            user_shares={recipient.id: SkillSharePermission.VIEWER},
        )
        replace_skill_bundle(
            skill=skill,
            ingested=second,
            base_version_id=None,
            user=author,
            skip_if_unchanged=False,
            db_session=db_session,
        )
        plugin = db_session.get(Plugin, skill.id)
        assert plugin is not None
        plugin.published_version_id = published_version_id
        plugin.installation_policy = PluginInstallationPolicy.DEFAULT
        db_session.flush()
        half = SKILL_RUNTIME_MAX_BYTES // 2
        _set_files(db_session, skill.id, [half, half + 1], resized)
        _set_files(
            db_session, skill.id, [_MB], resized, version_id=published_version_id
        )
        db_session.commit()

        recipient_payload = push.build_user_skills_payload(recipient, db_session)
        org_payload = push.build_user_skills_payload(org_only, db_session)

        [omission] = [
            item for item in recipient_payload.omissions if item.plugin_id == skill.id
        ]
        assert (omission.bytes, omission.files) == (2 * half + 1, 2)
        assert skill.id not in _omitted(org_payload)
        assert org_payload.files[f"{name}/notes.md"] == b"notes one"
    finally:
        delete_bundle_blob(file_store, first.bundle_file_id)
        delete_bundle_blob(file_store, second.bundle_file_id)


class _RecordingSandboxManager:
    def __init__(self) -> None:
        self.sent: list[UUID] = []

    def push_to_sandboxes(
        self, *, mount_path: str, sandbox_files: dict[UUID, dict[str, bytes]]
    ) -> SimpleNamespace:
        del mount_path
        self.sent.extend(sandbox_files)
        return SimpleNamespace(failures=[])


def test_omissions_are_recorded_and_a_backfilled_version_is_measured(
    db_session: Session,
    seeded_skill: Callable[..., Skill],
    resized: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, standard_account=True)
    db_session.commit()
    room = _free_room(db_session, user)
    tag = user.id.hex[:8]
    filler = seeded_skill(f"rt-filler-{tag}", author_user_id=user.id)
    small_files = seeded_skill(f"rt-small-{tag}", author_user_id=user.id)
    # Backfilled: no sizes. Its bundle is measured.
    backfilled = seeded_skill(f"rt-backfilled-{tag}", author_user_id=user.id)
    _turn_on(db_session, user, filler.id, _at(3))
    _turn_on(db_session, user, small_files.id, _at(2))
    _turn_on(db_session, user, backfilled.id, _at(1))
    # 50 bytes of room left: less than any SKILL.md.
    _set_files(db_session, filler.id, [room.bytes - 50], resized)
    _set_files(db_session, small_files.id, [1024] * 3, resized)
    resized.append(backfilled.id)
    sandbox = make_sandbox(db_session, user)
    db_session.commit()
    manager = _RecordingSandboxManager()
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)

    push.push_skills_for_users({user.id}, db_session)
    db_session.commit()

    db_session.refresh(sandbox)
    assert manager.sent == [sandbox.id]
    recorded = {item.plugin_id: item for item in sandbox.skill_omissions}
    assert recorded.keys() >= {small_files.id, backfilled.id}
    assert filler.id not in recorded
    small = recorded[small_files.id]
    assert (small.bytes, small.files, small.reason) == (3 * 1024, 3, "bytes")
    assert recorded[backfilled.id].files == 1
    assert recorded[backfilled.id].bytes > 50

    # Same content: no new send, and the record stays.
    push.push_skills_for_users({user.id}, db_session)
    db_session.commit()
    assert manager.sent == [sandbox.id]
    db_session.refresh(sandbox)
    assert {item.plugin_id for item in sandbox.skill_omissions} == set(recorded)


def test_file_count_limit(
    db_session: Session,
    seeded_skill: Callable[..., Skill],
    resized: list[UUID],
) -> None:
    user = make_user(db_session, standard_account=True)
    db_session.commit()
    room = _free_room(db_session, user)
    many = seeded_skill(f"rt-many-{user.id.hex[:8]}", author_user_id=user.id)
    _turn_on(db_session, user, many.id, _at(1))
    _set_files(db_session, many.id, [0] * (room.files + 1), resized)
    db_session.commit()

    [omission] = [
        item
        for item in push.build_user_skills_payload(user, db_session).omissions
        if item.plugin_id == many.id
    ]
    assert omission.reason == "files"
    assert omission.files == room.files + 1


def test_plugin_with_no_skills_is_not_pushed_or_left_out(
    db_session: Session,
    seeded_skill: Callable[..., Skill],
    resized: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user past the limits with a turned-on plugin that has no skills: the
    push sends nothing for it and the "did not load" list does not name it."""
    user = make_user(db_session, standard_account=True)
    db_session.commit()
    room = _free_room(db_session, user)
    tag = user.id.hex[:8]
    filler = seeded_skill(f"rt-nf-filler-{tag}", author_user_id=user.id)
    left_out = seeded_skill(f"rt-nf-left-{tag}", author_user_id=user.id)
    plugin = make_skillless_plugin(
        db_session, author_user_id=user.id, name=f"rt-nf-plugin-{tag}"
    )
    _turn_on(db_session, user, plugin.id, _at(4))
    _turn_on(db_session, user, filler.id, _at(3))
    _turn_on(db_session, user, left_out.id, _at(2))
    _set_files(db_session, filler.id, [room.bytes - 50], resized)
    _set_files(db_session, left_out.id, [1024], resized)
    sandbox = make_sandbox(db_session, user)
    db_session.commit()
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: _RecordingSandboxManager())

    push.push_skills_for_users({user.id}, db_session)
    db_session.commit()

    db_session.refresh(sandbox)
    recorded = {item.plugin_id for item in sandbox.skill_omissions}
    assert left_out.id in recorded
    assert plugin.id not in recorded
    payload = push.build_user_skills_payload(user, db_session)
    assert not any(path.startswith(f"{plugin.name}/") for path in payload.files)
    [listed] = [
        item for item in users_past_write_limit(db_session) if item.user_id == user.id
    ]
    assert listed.skills_not_loaded == len(recorded)


def test_admin_read_counts_skills_that_did_not_load(
    db_session: Session,
    seeded_skill: Callable[..., Skill],
    resized: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, standard_account=True)
    author = make_user(db_session, standard_account=True)
    db_session.commit()
    room = _free_room(db_session, user)
    big = [
        seeded_skill(f"rt-big{index}-{user.id.hex[:8]}", author_user_id=author.id)
        for index in range(3)
    ]
    for day, skill in enumerate(big, start=1):
        share_plugin_with_user(
            db_session, skill.id, user.id, SkillSharePermission.VIEWER
        )
        _turn_on(db_session, user, skill.id, _at(day))
        _set_files(db_session, skill.id, [room.bytes * 4 // 10], resized)
    db_session.commit()

    def listed() -> UserPastWriteLimit:
        [item] = [
            item
            for item in users_past_write_limit(db_session)
            if item.user_id == user.id
        ]
        return item

    # No sandbox yet: nothing was left out of one.
    assert listed().email == user.email
    assert listed().skills_not_loaded == 0

    make_sandbox(db_session, user)
    db_session.commit()
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: _RecordingSandboxManager())
    push.push_skills_for_users({user.id}, db_session)
    db_session.commit()
    assert listed().skills_not_loaded == 1
    payload = push.build_user_skills_payload(user, db_session)
    assert _omitted(payload) == {big[0].id}
