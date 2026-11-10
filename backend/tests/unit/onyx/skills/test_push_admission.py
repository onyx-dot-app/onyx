"""Receiver admission must not block fallback, other users, or session startup."""

import io
import tarfile
import zipfile
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Skill, SkillVersion, User
from onyx.file_store.file_store import FileStore
from onyx.server.features.build.sandbox.image.sandbox_daemon import extract
from onyx.server.features.build.sandbox.kubernetes import kubernetes_sandbox_manager
from onyx.server.features.build.sandbox.models import FatalWriteError, FileSet
from onyx.server.features.build.session import sandbox_lifecycle
from onyx.skills import bundle, push, validation
from tests.common.craft.stubs import StubSandboxManager


class SkillBundles:
    def __init__(self) -> None:
        self.bundles: dict[str, bytes] = {}
        self.reads: list[str] = []

    def add(
        self,
        name: str,
        body: bytes = b"Instructions",
        files: FileSet | None = None,
        *,
        valid: bool | None = True,
    ) -> Skill:
        bundle_id = str(uuid4())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "SKILL.md",
                f"---\nname: {name}\ndescription: Test\n---\n".encode() + body,
            )
            for path, content in (files or {}).items():
                archive.writestr(path, content)
        self.bundles[bundle_id] = stream.getvalue()
        version = SkillVersion(id=uuid4(), bundle_file_id=bundle_id, is_valid=valid)
        return Skill(
            id=uuid4(),
            name=name,
            current_version_id=version.id,
            current_version=version,
        )

    def read(self, file_id: str, **_kwargs: object) -> io.BytesIO:
        self.reads.append(file_id)
        return io.BytesIO(self.bundles[file_id])


@pytest.fixture
def bundles(monkeypatch: pytest.MonkeyPatch) -> SkillBundles:
    bundles = SkillBundles()
    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = bundles.read
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())
    monkeypatch.setattr(push, "get_connectable_apps_for_user", lambda *_args: [])
    return bundles


class ReceivingSandbox(StubSandboxManager):
    """Use the real tar encoder and receiver checks, without network I/O."""

    def __init__(self) -> None:
        super().__init__()
        self.delivered: dict[UUID, FileSet] = {}

    def write_files_to_sandbox(
        self, *, sandbox_id: UUID, mount_path: str, files: FileSet
    ) -> None:
        raw, _digest = kubernetes_sandbox_manager._build_targz(files)
        received: FileSet = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            total = 0
            for member in archive:
                extract._validate_member(member, mount_path)
                total += member.size
                if total > extract.MAX_BUNDLE_BYTES:
                    raise FatalWriteError("Receiver total exceeded")
                stream = archive.extractfile(member)
                assert stream is not None
                received[member.name] = stream.read()
        assert received == files
        self.delivered[sandbox_id] = received


@pytest.mark.parametrize("valid", [True, None])
@pytest.mark.parametrize("file_limit", ["DEFAULT_PER_FILE_MAX_BYTES", "MAX_FILE_BYTES"])
def test_oversized_winner_leaves_name_for_fallback(
    bundles: SkillBundles,
    monkeypatch: pytest.MonkeyPatch,
    valid: bool | None,
    file_limit: str,
) -> None:
    winner = bundles.add(
        "report", b"${CLAUDE_SKILL_DIR}" * 30, {"orphan.txt": b"omit"}, valid=valid
    )
    fallback = bundles.add("report", b"Fallback", {"kept.txt": b"keep"})
    loser = bundles.add("report", b"Never read")
    monkeypatch.setattr(push, file_limit, 800)
    replace = MagicMock(wraps=push.resolve_skill_dir_placeholder)
    monkeypatch.setattr(push, "resolve_skill_dir_placeholder", replace)

    files = push._assemble_fileset(
        [winner, fallback, loser], User(id=uuid4()), MagicMock(spec=Session)
    )

    assert set(files) == {"report/SKILL.md", "report/kept.txt"}
    assert files["report/SKILL.md"].endswith(b"Fallback")
    assert len(bundles.reads) == 2
    replace.assert_not_called()


@pytest.mark.parametrize("placeholder", [False, True])
@pytest.mark.parametrize("excess", [0, 1])
def test_aggregate_limit_uses_resolved_bytes_and_allows_fallback(
    bundles: SkillBundles,
    monkeypatch: pytest.MonkeyPatch,
    placeholder: bool,
    excess: int,
) -> None:
    body = b"${CLAUDE_SKILL_DIR}" if placeholder else b"Instructions"
    first = bundles.add("first", body, {"data": b"a" * 200})
    second = bundles.add("second", body, {"data": b"b" * 200})
    fallback = bundles.add("second", b"Fallback")
    db = MagicMock(spec=Session)
    user = User(id=uuid4())
    expected = push._assemble_fileset([first, second], user, db)
    total = sum(map(len, expected.values()))
    monkeypatch.setattr(push, "MAX_BUNDLE_BYTES", total - excess)
    replace = MagicMock(wraps=push.resolve_skill_dir_placeholder)
    monkeypatch.setattr(push, "resolve_skill_dir_placeholder", replace)

    files = push._assemble_fileset([first, second, fallback], user, db)

    assert sum(map(len, files.values())) <= total - excess
    if excess:
        assert "second/data" not in files
        assert files["second/SKILL.md"].endswith(b"Fallback")
    else:
        assert files == expected
    assert replace.call_count == (2 - excess if placeholder else 0)


def test_receiver_accepts_assembled_payload_at_real_100_mib_limit(
    bundles: SkillBundles, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert push.MAX_BUNDLE_BYTES == extract.MAX_BUNDLE_BYTES == 100 * 1024 * 1024
    skills = [
        bundles.add(f"skill-{index}", files={"data": b"x" * (20 * 1024 * 1024)})
        for index in range(6)
    ]
    files = push._assemble_fileset(skills, User(id=uuid4()), MagicMock(spec=Session))
    raw, _digest = kubernetes_sandbox_manager._build_targz(files)
    assert set(files) == {
        f"skill-{index}/{name}" for index in range(4) for name in ("SKILL.md", "data")
    }
    monkeypatch.setattr(extract, "ALLOWED_PREFIX", str(tmp_path) + "/")
    mount = tmp_path / "skills"
    extract.safe_extract_then_atomic_swap(raw, str(mount))
    assert mount.is_symlink()
    assert (mount / "skill-3/data").stat().st_size == 20 * 1024 * 1024
    assert not (mount / "skill-4").exists()


@pytest.mark.parametrize("all_omitted", [False, True])
@pytest.mark.parametrize("operation", ["batch", "startup"])
def test_oversized_user_does_not_abort_batch_or_startup(
    bundles: SkillBundles,
    monkeypatch: pytest.MonkeyPatch,
    all_omitted: bool,
    operation: str,
) -> None:
    first = bundles.add("first", files={"data": b"a" * 200})
    second = bundles.add("second", files={"data": b"b" * 200})
    normal = bundles.add("normal")
    users = [User(id=uuid4()), User(id=uuid4())]
    sandboxes = {uuid4(): user for user in users}
    skills = {users[0].id: [first, second], users[1].id: [normal]}

    def resolve(user: User, **_kwargs: object) -> list[Skill]:
        return skills[user.id]

    limit = 100 if all_omitted else 400
    monkeypatch.setattr(push, "MAX_BUNDLE_BYTES", limit)
    monkeypatch.setattr(extract, "MAX_BUNDLE_BYTES", limit)
    monkeypatch.setattr(push, "list_runtime_skills_for_user", resolve)
    monkeypatch.setattr(push, "get_sandbox_user_map", lambda *_args: sandboxes)
    monkeypatch.setattr(push, "lock_sandbox_skills_hashes", lambda *_args: {})
    record = MagicMock()
    monkeypatch.setattr(push, "set_sandbox_skills_hashes__no_commit", record)
    manager = ReceivingSandbox()
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)
    db = MagicMock(spec=Session)
    apps_section = push.build_connectable_apps_list([])
    expected = set() if all_omitted else {"first/SKILL.md", "first/data"}

    if operation == "startup":
        monkeypatch.setattr(
            sandbox_lifecycle, "resolve_craft_mcp_servers", lambda *_args: []
        )
        monkeypatch.setattr(
            sandbox_lifecycle, "build_user_library_fileset", lambda *_args: {}
        )
        payload = sandbox_lifecycle.build_managed_content_payload(users[0], db)
        assert set(payload.skills_files) == expected
        assert payload.skills_hash == push.compute_skill_runtime_hash(
            payload.skills_files, apps_section
        )
        return

    push.push_skills_for_users({user.id for user in users}, db)

    assert set(manager.delivered) == set(sandboxes)
    first_id, normal_id = sandboxes
    assert set(manager.delivered[first_id]) == expected
    assert set(manager.delivered[normal_id]) == {"normal/SKILL.md"}
    record.assert_called_once_with(
        db,
        {
            sandbox_id: push.compute_skill_runtime_hash(files, apps_section)
            for sandbox_id, files in manager.delivered.items()
        },
    )


@pytest.fixture
def raised_upload_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    """Allow stored files above the receiver cap without changing receiver limits."""
    limit = 32 * 1024 * 1024
    monkeypatch.setattr(push, "DEFAULT_PER_FILE_MAX_BYTES", limit)
    monkeypatch.setattr(bundle, "DEFAULT_PER_FILE_MAX_BYTES", limit)
    monkeypatch.setattr(
        validation,
        "normalize_custom_bundle",
        partial(bundle.normalize_custom_bundle, per_file_max_bytes=limit),
    )
    return limit


@pytest.mark.parametrize("valid", [True, None])
@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("kind", ["sibling", "instructions", "expanded-instructions"])
def test_receiver_file_boundary_preserves_fallback_and_other_users(
    bundles: SkillBundles,
    raised_upload_cap: int,
    monkeypatch: pytest.MonkeyPatch,
    valid: bool | None,
    offset: int,
    kind: str,
) -> None:
    receiver_limit = 25 * 1024 * 1024
    assert push.MAX_FILE_BYTES == extract.MAX_FILE_BYTES == receiver_limit
    assert raised_upload_cap > receiver_limit
    name = "report"
    header = f"---\nname: {name}\ndescription: Test\n---\n".encode()
    target_size = receiver_limit + offset
    if kind == "sibling":
        body = b"${CLAUDE_SKILL_DIR}/run.py"
        siblings = {"references/data.bin": b"x" * target_size}
    else:
        placeholder = b"${CLAUDE_SKILL_DIR}" if kind == "expanded-instructions" else b""
        growth = len(f"{push.SKILLS_MOUNT_PATH}/{name}".encode()) - len(placeholder)
        body = placeholder + b"x" * (
            target_size
            - len(header)
            - len(placeholder)
            - (growth if placeholder else 0)
        )
        siblings = {"orphan.txt": b"omit with oversized candidate"}
    unavailable = bundles.add(name, valid=False)
    candidate = bundles.add(name, body, siblings, valid=valid)
    fallback = bundles.add(name, b"Fallback", {"kept.txt": b"keep"})
    normal = bundles.add("normal")
    users = [User(id=uuid4()), User(id=uuid4())]
    sandboxes = {uuid4(): user for user in users}
    skills = {users[0].id: [unavailable, candidate, fallback], users[1].id: [normal]}

    def resolve(user: User, **_kwargs: object) -> list[Skill]:
        return skills[user.id]

    monkeypatch.setattr(push, "list_runtime_skills_for_user", resolve)
    monkeypatch.setattr(push, "get_sandbox_user_map", lambda *_args: sandboxes)
    monkeypatch.setattr(push, "lock_sandbox_skills_hashes", lambda *_args: {})
    record = MagicMock()
    monkeypatch.setattr(push, "set_sandbox_skills_hashes__no_commit", record)
    replace = MagicMock(wraps=push.resolve_skill_dir_placeholder)
    monkeypatch.setattr(push, "resolve_skill_dir_placeholder", replace)
    manager = ReceivingSandbox()
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)
    db = MagicMock(spec=Session)

    push.push_skills_for_users({user.id for user in users}, db)

    assert set(manager.delivered) == set(sandboxes)
    first_id, normal_id = sandboxes
    files = manager.delivered[first_id]
    if offset > 0:
        assert set(files) == {"report/SKILL.md", "report/kept.txt"}
        assert files["report/SKILL.md"].endswith(b"Fallback")
        replace.assert_not_called()
    else:
        measured_path = (
            "report/references/data.bin" if kind == "sibling" else "report/SKILL.md"
        )
        assert len(files[measured_path]) == target_size
        assert "report/kept.txt" not in files
    assert set(manager.delivered[normal_id]) == {"normal/SKILL.md"}
    assert len(bundles.reads) == (3 if offset > 0 else 2)
    record.assert_called_once_with(
        db,
        {
            sandbox_id: push.compute_skill_runtime_hash(
                files, push.build_connectable_apps_list([])
            )
            for sandbox_id, files in manager.delivered.items()
        },
    )
