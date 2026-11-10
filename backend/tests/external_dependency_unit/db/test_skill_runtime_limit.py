"""Runtime disk limit: whole Skills in keep order, with real stored bundles."""

import io
import zipfile
from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4
from weakref import ReferenceType, ref

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db import skill as skill_db
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import Sandbox, Skill, User, UserSkillPreference
from onyx.db.skill import SkillRuntimePriority, list_runtime_skill_candidates_for_user
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.sandbox.models import FileSet, PushResult
from onyx.server.features.build.session.sandbox_lifecycle import (
    build_managed_content_payload,
)
from onyx.skills import built_in as built_in_module
from onyx.skills import push
from onyx.skills.built_in import BuiltInSkillDefinition
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_built_in_skill_row,
    make_group,
    make_sandbox,
    make_skill,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context")
MIB = 1024 * 1024
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
StoreSkill = Callable[..., Skill]


@pytest.fixture
def store_skill(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[StoreSkill, None, None]:
    """Hide other Skills in this transaction and save real bundles for new ones."""
    session.execute(update(Skill).values(retired_at=NOW))
    monkeypatch.setattr(skill_db, "BUILT_IN_SKILLS", {})
    monkeypatch.setattr(push, "BUILT_IN_SKILLS", skill_db.BUILT_IN_SKILLS)
    file_store = get_default_file_store()
    file_store.initialize()
    saved: list[str] = []

    def store(
        *,
        name: str | None = None,
        files: dict[str, bytes] | None = None,
        policy: Policy = Policy.DEFAULT,
        is_public: bool = False,
        author_user_id: UUID | None = None,
    ) -> Skill:
        name = name or f"runtime-{uuid4().hex[:8]}"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("SKILL.md", f"---\nname: {name}\ndescription: d\n---\n")
            for path, content in (files or {}).items():
                bundle.writestr(path, content)
        file_id = file_store.save_file(
            content=io.BytesIO(output.getvalue()),
            display_name=f"{name}.zip",
            file_origin=FileOrigin.SKILL_BUNDLE,
            file_type="application/zip",
        )
        saved.append(file_id)
        skill = make_skill(
            session,
            name=name,
            bundle_file_id=file_id,
            is_valid=True,
            is_public=is_public,
            author_user_id=author_user_id,
        )
        skill.installation_policy = policy
        session.flush()
        return skill

    yield store
    for file_id in saved:
        file_store.delete_file(file_id, error_on_missing=False)


def _enable(session: Session, user: User, skill: Skill, at: datetime | None) -> None:
    session.add(
        UserSkillPreference(
            user_id=user.id,
            skill_id=skill.id,
            name=skill.name,
            enabled=True,
            enabled_at=at,
        )
    )
    session.flush()


def _charge(files: FileSet, name: str) -> tuple[int, int]:
    sizes = [len(b) for path, b in files.items() if path.startswith(f"{name}/")]
    return sum(max(size, 4096) for size in sizes), len(sizes)


def _names(files: FileSet) -> set[str]:
    return {path.split("/", 1)[0] for path in files}


def test_keep_order_uses_class_then_newest_date(
    session: Session,
    store_skill: StoreSkill,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(session, standard_account=True)
    group = make_group(session)
    add_user_to_group(session, user, group)
    monkeypatch.setattr(built_in_module, "BUILTIN_SKILLS_PATH", tmp_path)
    built_in_id = f"runtime-builtin-{uuid4().hex[:8]}"
    (tmp_path / built_in_id).mkdir()
    (tmp_path / built_in_id / "SKILL.md").write_text(f"---\nname: {built_in_id}\n---\n")
    skill_db.BUILT_IN_SKILLS[built_in_id] = BuiltInSkillDefinition(
        built_in_skill_id=built_in_id
    )
    built_in = make_built_in_skill_row(session, built_in_skill_id=built_in_id)

    required = store_skill(is_public=True, policy=Policy.REQUIRED)
    _enable(session, user, required, NOW)  # Required outranks an explicit enable.
    enabled_new = store_skill(is_public=True, policy=Policy.AVAILABLE)
    _enable(session, user, enabled_new, NOW)
    reenabled_default = store_skill(is_public=True)
    _enable(session, user, reenabled_default, NOW - timedelta(days=1))
    enabled_legacy = store_skill(author_user_id=user.id)
    _enable(session, user, enabled_legacy, None)
    group_new = store_skill()
    share_skill_with_group(session, group_new, group).created_at = NOW
    direct_old = store_skill()
    share_skill_with_user(session, direct_old, user).created_at = NOW - timedelta(
        days=2
    )
    both = store_skill()
    share_skill_with_user(session, both, user).created_at = NOW - timedelta(days=9)
    share_skill_with_group(session, both, group).created_at = NOW - timedelta(days=1)
    legacy_b = store_skill(name=f"z-legacy-{uuid4().hex[:6]}", is_public=True)
    legacy_a = store_skill(name=f"a-legacy-{uuid4().hex[:6]}", is_public=True)
    session.flush()

    candidates = list_runtime_skill_candidates_for_user(user=user, db_session=session)
    by_rank = sorted(candidates, key=lambda candidate: candidate.keep_rank)
    expected = [
        (built_in, SkillRuntimePriority.BUILT_IN),
        (required, SkillRuntimePriority.REQUIRED),
        (enabled_new, SkillRuntimePriority.ENABLED),
        (reenabled_default, SkillRuntimePriority.ENABLED),
        (enabled_legacy, SkillRuntimePriority.ENABLED),
        (group_new, SkillRuntimePriority.DEFAULT),
        (both, SkillRuntimePriority.DEFAULT),
        (direct_old, SkillRuntimePriority.DEFAULT),
        (legacy_a, SkillRuntimePriority.DEFAULT),
        (legacy_b, SkillRuntimePriority.DEFAULT),
    ]
    assert [(c.skill.id, c.priority) for c in by_rank] == [
        (skill.id, priority) for skill, priority in expected
    ]
    assert [c.keep_rank for c in by_rank] == list(range(1, len(expected) + 1))
    assert by_rank[6].granted_at == NOW - timedelta(days=1)

    # Each rendered file here is under 4 KiB, so each Skill charges 4096 bytes.
    monkeypatch.setattr(push, "SKILL_RUNTIME_MAX_FILES", 4)
    payload = push.build_user_skills_payload(user, session)
    assert _names(payload.files) == {skill.name for skill, _ in expected[:4]}
    assert [(o.skill_id, o.charged_bytes, o.file_count) for o in payload.omissions] == [
        (skill.id, 4096, 1) for skill, _ in expected[4:]
    ]
    assert {o.failed_limit for o in payload.omissions} == {push.SkillRuntimeLimit.FILES}


def test_exact_limits_charge_blocks_and_try_smaller_later_skills(
    session: Session, store_skill: StoreSkill, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(session, standard_account=True)
    first = store_skill(author_user_id=user.id, files={"big.bin": b"x" * 10_000})
    large = store_skill(
        author_user_id=user.id, files={f"{i}.txt": b"y" for i in range(3)}
    )
    small = store_skill(author_user_id=user.id, files={"tiny.txt": b"z"})
    for days, skill in enumerate((first, large, small)):
        _enable(session, user, skill, NOW - timedelta(days=days))

    full = push.build_skills_fileset_for_user(user, session)
    first_bytes, first_files = _charge(full, first.name)
    large_bytes, large_files = _charge(full, large.name)
    small_bytes, small_files = _charge(full, small.name)
    assert first_bytes == len(full[f"{first.name}/big.bin"]) + 4096
    assert (large_bytes, large_files) == (4 * 4096, 4)
    assert (small_bytes, small_files) == (2 * 4096, 2)

    monkeypatch.setattr(push, "SKILL_RUNTIME_MAX_BYTES", first_bytes + small_bytes)
    payload = push.build_user_skills_payload(user, session)
    assert _names(payload.files) == {first.name, small.name}
    assert payload.omissions == (
        push.SkillRuntimeOmission(
            skill_id=large.id,
            name=large.name,
            charged_bytes=large_bytes,
            file_count=large_files,
            failed_limit=push.SkillRuntimeLimit.BYTES,
        ),
    )
    monkeypatch.setattr(
        push, "SKILL_RUNTIME_MAX_BYTES", first_bytes + large_bytes + small_bytes
    )
    assert push.build_user_skills_payload(user, session).files == full
    monkeypatch.setattr(
        push, "SKILL_RUNTIME_MAX_BYTES", first_bytes + large_bytes + small_bytes - 1
    )
    payload = push.build_user_skills_payload(user, session)
    assert [o.skill_id for o in payload.omissions] == [small.id]
    monkeypatch.setattr(push, "SKILL_RUNTIME_MAX_BYTES", 900 * MIB)
    monkeypatch.setattr(
        push, "SKILL_RUNTIME_MAX_FILES", first_files + large_files + small_files - 1
    )
    payload = push.build_user_skills_payload(user, session)
    assert _names(payload.files) == {first.name, large.name}
    assert [(o.skill_id, o.failed_limit) for o in payload.omissions] == [
        (small.id, push.SkillRuntimeLimit.FILES)
    ]


@pytest.mark.parametrize("winner_readable", [False, True])
def test_fallback_uses_delivered_candidate_rank_without_substitution(
    session: Session,
    store_skill: StoreSkill,
    monkeypatch: pytest.MonkeyPatch,
    winner_readable: bool,
) -> None:
    user = make_user(session, standard_account=True)
    # The company winner is a late Default; the hidden own duplicate is newest.
    company = store_skill(is_public=True)
    own = store_skill(name=company.name, author_user_id=user.id)
    _enable(session, user, own, NOW)
    middle = store_skill(author_user_id=user.id)
    _enable(session, user, middle, NOW - timedelta(days=1))
    assert company.current_version is not None
    if not winner_readable:
        company.current_version.bundle_file_id = None
    session.flush()
    monkeypatch.setattr(push, "SKILL_RUNTIME_MAX_FILES", 1)
    store = MagicMock(wraps=get_default_file_store())
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)

    payload = push.build_user_skills_payload(user, session)

    reads = [call.args[0] for call in store.read_file.call_args_list]
    assert own.current_version is not None and middle.current_version is not None
    if winner_readable:
        # The company copy ranks after middle, is omitted, and never swaps to own.
        assert _names(payload.files) == {middle.name}
        assert [(o.skill_id, o.name) for o in payload.omissions] == [
            (company.id, company.name)
        ]
        assert own.current_version.bundle_file_id not in reads
        assert reads.count(company.current_version.bundle_file_id) == 2
    else:
        # The delivered own copy keeps its own newer explicit rank.
        assert payload.files[f"{own.name}/SKILL.md"].startswith(b"---\n")
        assert _names(payload.files) == {own.name}
        assert [o.skill_id for o in payload.omissions] == [middle.id]
        assert reads.count(own.current_version.bundle_file_id) == 1


def test_session_start_and_three_sandbox_push_share_one_bounded_payload(
    session: Session, store_skill: StoreSkill, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(push, "SKILL_RUNTIME_MAX_FILES", 2)
    users = [make_user(session, standard_account=True) for _ in range(3)]
    sandboxes: dict[UUID, Sandbox] = {}
    for user in users:
        for days in range(3):
            skill = store_skill(author_user_id=user.id)
            _enable(session, user, skill, NOW - timedelta(days=days))
        sandboxes[user.id] = make_sandbox(session, user, status=SandboxStatus.RUNNING)

    start = build_managed_content_payload(users[0], session)
    runtime = push.build_user_skills_payload(users[0], session)
    assert start.skills_files == runtime.files
    assert start.skill_omissions == runtime.omissions and len(runtime.omissions) == 1
    assert start.skills_hash == push.compute_skill_runtime_hash(
        runtime.files, runtime.connectable_apps_section
    )
    del start, runtime

    refs: list[ReferenceType[push.UserSkillsPayload]] = []
    live_at_build: list[int] = []
    sent: dict[UUID, FileSet] = {}
    apps: dict[UUID, str] = {}
    build = push.build_user_skills_payload

    def tracked(user: User, db_session: Session) -> push.UserSkillsPayload:
        live_at_build.append(sum(reference() is not None for reference in refs))
        payload = build(user, db_session)
        refs.append(ref(payload))
        apps[sandboxes[user.id].id] = payload.connectable_apps_section
        return payload

    def send(
        *, sandbox_id: UUID, mount_path: str, files: FileSet, timeout_s: float = 30.0
    ) -> PushResult:
        assert mount_path == push.SKILLS_MOUNT_PATH and timeout_s > 0
        sent[sandbox_id] = dict(files)
        return PushResult(targets=1, succeeded=1, failures=[])

    manager = StubSandboxManager()
    monkeypatch.setattr(manager, "push_to_sandbox", send)
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(push, "build_user_skills_payload", tracked)
    push.push_skills_for_users({user.id for user in users}, session)

    assert live_at_build == [0, 0, 0]
    assert all(reference() is None for reference in refs)
    assert set(sent) == {sandbox.id for sandbox in sandboxes.values()}
    for files in sent.values():
        assert len(files) == 2
    for sandbox in sandboxes.values():
        session.refresh(sandbox)
        assert sandbox.skills_hash == push.compute_skill_runtime_hash(
            sent[sandbox.id], apps[sandbox.id]
        )
        # The oldest enabled Skill is the one the file limit left out.
        assert [o.failed_limit for o in sandbox.skill_runtime_omissions] == [
            push.SkillRuntimeLimit.FILES
        ]
        assert not any(
            path.startswith(f"{sandbox.skill_runtime_omissions[0].name}/")
            for path in sent[sandbox.id]
        )


def test_group_join_past_write_limit_still_loads_every_fitting_skill(
    session: Session, store_skill: StoreSkill
) -> None:
    """Six real 96 MiB Skills: 576 MiB is past 500 MB and within 900 MiB."""
    user = make_user(session, standard_account=True)
    group = make_group(session)
    chunk = b"onyx runtime limit evidence\n" * (24 * MIB // 28)
    skills = []
    for _ in range(6):
        skill = store_skill(files={f"part-{i}.txt": chunk for i in range(4)})
        share_skill_with_group(session, skill, group)
        skills.append(skill)
    assert push.build_user_skills_payload(user, session).files == {}

    add_user_to_group(session, user, group)
    payload = push.build_user_skills_payload(user, session)

    actual_bytes = sum(len(content) for content in payload.files.values())
    print(
        f"group-join runtime payload: {actual_bytes} bytes, {len(payload.files)} files"
    )
    assert payload.omissions == ()
    assert _names(payload.files) == {skill.name for skill in skills}
    assert 500 * 1000 * 1000 < actual_bytes < push.SKILL_RUNTIME_MAX_BYTES
    assert len(payload.files) == 30


def test_implied_directory_limit_omits_whole_skill_and_keeps_smaller(
    session: Session, store_skill: StoreSkill, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(session, standard_account=True)
    first = store_skill(
        author_user_id=user.id, files={"a/b/one": b"x", "a/b/two": b"y"}
    )
    crowded = store_skill(author_user_id=user.id, files={"c/d/file": b"x"})
    small = store_skill(author_user_id=user.id, files={"c/file": b"x"})
    for days, skill in enumerate((first, crowded, small)):
        _enable(session, user, skill, NOW - timedelta(days=days))
    # first uses three unique folders; small uses two. Shared parents count once.
    monkeypatch.setattr(push, "PUSH_MAX_DIRECTORIES", 5, raising=False)
    payload = push.build_user_skills_payload(user, session)
    assert _names(payload.files) == {first.name, small.name}
    assert [(o.skill_id, o.failed_limit.value) for o in payload.omissions] == [
        (crowded.id, "directories")
    ]


def test_runtime_path_limit_omits_whole_skill_and_keeps_other_names(
    session: Session, store_skill: StoreSkill, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(session, standard_account=True)
    long_path = store_skill(author_user_id=user.id, files={"é" * 50: b"x"})
    small = store_skill(author_user_id=user.id)
    _enable(session, user, long_path, NOW)
    _enable(session, user, small, NOW - timedelta(days=1))
    monkeypatch.setattr(push, "SKILL_RUNTIME_MAX_PATH_BYTES", 100, raising=False)
    payload = push.build_user_skills_payload(user, session)
    assert _names(payload.files) == {small.name}
    assert [(o.skill_id, o.failed_limit.value) for o in payload.omissions] == [
        (long_path.id, "paths")
    ]


@pytest.mark.parametrize(
    "path", ["a" * 256, "é" * 128, "/".join(["a" * 200] * 20 + ["b" * 40])]
)
def test_runtime_filesystem_limits_omit_whole_skill(
    session: Session, store_skill: StoreSkill, path: str
) -> None:
    user = make_user(session, standard_account=True)
    oversized = store_skill(author_user_id=user.id, files={path: b"x"})
    small = store_skill(author_user_id=user.id)
    _enable(session, user, oversized, NOW)
    _enable(session, user, small, NOW - timedelta(days=1))
    payload = push.build_user_skills_payload(user, session)
    assert _names(payload.files) == {small.name}
    assert [(o.skill_id, o.failed_limit.value) for o in payload.omissions] == [
        (oversized.id, "paths")
    ]


@pytest.mark.parametrize("extra_byte", [0, 1])
def test_runtime_paths_fit_session_symlink(
    session: Session, store_skill: StoreSkill, extra_byte: int
) -> None:
    user = make_user(session, standard_account=True)
    # Include the Skill name: the longest session-relative path is 4,021 bytes.
    name = "session-path"
    prefix = "/".join(["a" * 200] * 19) + "/"
    leaf_size = 4021 + extra_byte - len(name) - 1 - len(prefix)
    path = prefix + "b" * leaf_size
    skill = store_skill(name=name, author_user_id=user.id, files={path: b"readable"})
    _enable(session, user, skill, NOW)
    payload = push.build_user_skills_payload(user, session)
    if extra_byte:
        assert payload.files == {}
        assert [(o.skill_id, o.failed_limit.value) for o in payload.omissions] == [
            (skill.id, "paths")
        ]
    else:
        assert payload.files[f"{name}/{path}"] == b"readable"
        assert payload.omissions == ()
