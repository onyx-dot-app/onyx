"""Cluster B — Skill push end-to-end.

These tests pin the contract for the push pipeline:

- ``push_skill_to_affected_sandboxes`` — resolve affected users + push.
- ``push_skills_for_users`` — rebuild + push fileset for a set of users.
- ``hydrate_sandbox_skills`` — single-sandbox cold-start hydration.
- ``build_skills_fileset_for_user`` — exercised transitively.

All tests run against real Postgres and a real ``LocalSandboxManager`` bound
to ``tmp_path``. We assert observable outcomes only — files on disk, file
contents, log records. The single sanctioned mock is ``StubSandboxManager``
in ``test_one_failing_sandbox_does_not_abort_push_to_others``, used to inject
a ``FatalWriteError`` we cannot reproduce against the real filesystem.
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Callable
from collections.abc import Generator
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.db.enums import AccessType
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import delete_skill
from onyx.db.skill import patch_skill
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_grants
from onyx.db.skill import SkillPatch
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SKILLS_TEMPLATE_PATH
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.skills.push import hydrate_sandbox_skills
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users
from onyx.skills.registry import BuiltinSkillRegistry
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import make_cc_pair
from tests.external_dependency_unit.craft._test_helpers import make_group
from tests.external_dependency_unit.craft._test_helpers import make_user
from tests.external_dependency_unit.craft.conftest import SandboxHandle
from tests.external_dependency_unit.craft.stubs import StubSandboxManager


def _provision_with_status(
    handle: SandboxHandle,
    db_session: Session,
    user: User,
    status: SandboxStatus = SandboxStatus.RUNNING,
) -> tuple[Sandbox, Path]:
    """Provision a sandbox for ``user`` via ``handle``, optionally overriding status.

    Returns ``(sandbox_row, workspace_path)``. If ``status`` is not RUNNING the
    row is updated after provisioning (the manager always starts with RUNNING).
    """
    workspace = handle.provision_for(user)
    row = (
        db_session.query(Sandbox)
        .filter(Sandbox.user_id == user.id)
        .order_by(Sandbox.created_at.desc())
        .first()
    )
    assert row is not None
    if status != SandboxStatus.RUNNING:
        row.status = status
        db_session.commit()
    return row, workspace


def _skill_file_path(workspace: Path, slug: str, name: str = "SKILL.md") -> Path:
    return workspace / "managed" / "skills" / slug / name


def _skills_dir(workspace: Path) -> Path:
    return workspace / "managed" / "skills"


# =============================================================================
# Registry hygiene — keep the process-wide singleton clean between tests.
# =============================================================================


@pytest.fixture(scope="function")
def fresh_registry() -> Generator[BuiltinSkillRegistry, None, None]:
    """Yield a fresh, empty BuiltinSkillRegistry singleton for the test."""
    BuiltinSkillRegistry._reset_for_testing()
    yield BuiltinSkillRegistry.instance()
    BuiltinSkillRegistry._reset_for_testing()


# =============================================================================
# Tests
# =============================================================================


class TestSkillPush:
    def test_public_skill_lands_in_every_running_sandbox(
        self,
        db_session: Session,
        granted_users: Callable[..., dict[str, list[User]]],
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        cohort = granted_users(
            grants={"engineering": [None], "sales": [None], "noone": [None]}
        )
        user_a = cohort["engineering"][0]
        user_b = cohort["sales"][0]
        user_c = cohort["noone"][0]

        # Delete sandbox rows created by granted_users (they lack FS
        # provisioning) and re-provision via handle.provision_for.
        workspaces: dict[UUID, Path] = {}
        for user in (user_a, user_b, user_c):
            row = db_session.query(Sandbox).filter(Sandbox.user_id == user.id).one()
            db_session.delete(row)
        db_session.commit()
        for user in (user_a, user_b, user_c):
            workspaces[user.id] = handle.provision_for(user)

        public_skill = seeded_skill(
            slug=f"public-skill-{uuid4().hex[:6]}",
            public=True,
            bundle_files={"SKILL.md": "public skill body\n"},
        )

        push_skill_to_affected_sandboxes(public_skill, db_session)

        for user_id, workspace in workspaces.items():
            skill_md = _skill_file_path(workspace, public_skill.slug)
            assert skill_md.exists(), (
                f"Expected SKILL.md in {workspace} for user {user_id}"
            )
            assert skill_md.read_bytes() == b"public skill body\n"

    def test_private_skill_only_lands_in_granted_users_sandboxes(
        self,
        db_session: Session,
        granted_users: Callable[..., dict[str, list[User]]],
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        cohort = granted_users(
            grants={"engineering": [None], "sales": [None], "noone": [None]}
        )
        user_a = cohort["engineering"][0]
        user_b = cohort["sales"][0]
        user_c = cohort["noone"][0]
        eng_group = (
            db_session.query(UserGroup).filter(UserGroup.name == "engineering").one()
        )

        workspaces: dict[UUID, Path] = {}
        for user in (user_a, user_b, user_c):
            row = db_session.query(Sandbox).filter(Sandbox.user_id == user.id).one()
            db_session.delete(row)
        db_session.commit()
        for user in (user_a, user_b, user_c):
            workspaces[user.id] = handle.provision_for(user)

        skill = seeded_skill(
            slug=f"eng-only-{uuid4().hex[:6]}",
            public=False,
            groups=[eng_group],
            bundle_files={"SKILL.md": "engineering only\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)

        assert _skill_file_path(workspaces[user_a.id], skill.slug).exists()
        assert not _skill_file_path(workspaces[user_b.id], skill.slug).exists()
        assert not _skill_file_path(workspaces[user_c.id], skill.slug).exists()

    def test_push_skips_sleeping_sandboxes(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user = make_user(db_session)
        db_session.commit()
        _row, workspace = _provision_with_status(
            handle, db_session, user, status=SandboxStatus.SLEEPING
        )

        skill = seeded_skill(
            slug=f"sleeping-{uuid4().hex[:6]}",
            public=True,
            bundle_files={"SKILL.md": "anything\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)

        # Workspace dir exists (we provisioned it) but no managed/skills/.
        assert workspace.exists()
        assert not _skills_dir(workspace).exists()

    def test_push_skips_terminated_sandboxes(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user = make_user(db_session)
        db_session.commit()
        _row, workspace = _provision_with_status(
            handle, db_session, user, status=SandboxStatus.TERMINATED
        )

        skill = seeded_skill(
            slug=f"terminated-{uuid4().hex[:6]}",
            public=True,
            bundle_files={"SKILL.md": "anything\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)

        assert workspace.exists()
        assert not _skills_dir(workspace).exists()

    def test_disable_skill_removes_files_from_affected_sandboxes(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user = make_user(db_session)
        group = make_group(db_session, name=f"disable-grp-{uuid4().hex[:6]}")
        add_user_to_group(db_session, user, group)
        db_session.commit()

        _row, workspace = _provision_with_status(handle, db_session, user)

        skill = seeded_skill(
            slug=f"disable-me-{uuid4().hex[:6]}",
            public=False,
            groups=[group],
            bundle_files={"SKILL.md": "to be disabled\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)
        assert _skill_file_path(workspace, skill.slug).exists()

        patch_skill(
            skill_id=skill.id,
            patch=SkillPatch(enabled=False),
            db_session=db_session,
        )
        db_session.commit()

        push_skill_to_affected_sandboxes(skill, db_session)

        # Skill directory must be gone after the disable + push cycle.
        assert not (_skills_dir(workspace) / skill.slug).exists()

    def test_grants_change_adds_to_newly_granted_and_removes_from_revoked(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user_a = make_user(db_session)
        user_b = make_user(db_session)
        group_x = make_group(db_session, name=f"grp-x-{uuid4().hex[:6]}")
        group_y = make_group(db_session, name=f"grp-y-{uuid4().hex[:6]}")
        add_user_to_group(db_session, user_a, group_x)
        add_user_to_group(db_session, user_b, group_y)
        db_session.commit()

        _row_a, ws_a = _provision_with_status(handle, db_session, user_a)
        _row_b, ws_b = _provision_with_status(handle, db_session, user_b)

        skill = seeded_skill(
            slug=f"grants-flip-{uuid4().hex[:6]}",
            public=False,
            groups=[group_x],
            bundle_files={"SKILL.md": "shifting grants\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)
        assert _skill_file_path(ws_a, skill.slug).exists()
        assert not _skill_file_path(ws_b, skill.slug).exists()

        # Re-push must target the union of OLD and NEW affected users — old
        # so we remove from them, new so we add for them.
        old_affected = affected_user_ids_for_skill(skill, db_session)

        replace_skill_grants(
            skill_id=skill.id,
            group_ids=[group_y.id],
            db_session=db_session,
        )
        db_session.commit()
        db_session.refresh(skill)

        new_affected = affected_user_ids_for_skill(skill, db_session)
        push_skills_for_users(old_affected | new_affected, db_session)

        assert not _skill_file_path(ws_a, skill.slug).exists()
        assert _skill_file_path(ws_b, skill.slug).exists()

    def test_replace_bundle_propagates_new_content(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        seeded_bundle: Callable[[dict[str, bytes | str]], bytes],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user = make_user(db_session)
        db_session.commit()
        _row, workspace = _provision_with_status(handle, db_session, user)

        skill = seeded_skill(
            slug=f"versioned-{uuid4().hex[:6]}",
            public=True,
            bundle_files={"SKILL.md": "version one\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)
        assert _skill_file_path(workspace, skill.slug).read_bytes() == b"version one\n"

        # Replace the bundle blob, then point the skill row at the new one.
        v2_bytes = seeded_bundle({"SKILL.md": "version two\n"})
        file_store = get_default_file_store()
        new_file_id = file_store.save_file(
            content=io.BytesIO(v2_bytes),
            display_name=f"{skill.slug}-v2.zip",
            file_origin=FileOrigin.SKILL_BUNDLE,
            file_type="application/zip",
        )
        replace_skill_bundle(
            skill_id=skill.id,
            new_bundle_file_id=new_file_id,
            new_bundle_sha256=hashlib.sha256(v2_bytes).hexdigest(),
            db_session=db_session,
        )
        db_session.commit()

        push_skill_to_affected_sandboxes(skill, db_session)

        assert _skill_file_path(workspace, skill.slug).read_bytes() == b"version two\n"

    def test_delete_skill_removes_directory_from_all_affected_sandboxes(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user_a = make_user(db_session)
        user_b = make_user(db_session)
        db_session.commit()
        _row_a, ws_a = _provision_with_status(handle, db_session, user_a)
        _row_b, ws_b = _provision_with_status(handle, db_session, user_b)

        skill = seeded_skill(
            slug=f"to-delete-{uuid4().hex[:6]}",
            public=True,
            bundle_files={"SKILL.md": "will be deleted\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)
        assert _skill_file_path(ws_a, skill.slug).exists()
        assert _skill_file_path(ws_b, skill.slug).exists()

        # Capture affected users BEFORE delete — after delete the skill row
        # is gone and the resolver has nothing to walk from.
        affected = affected_user_ids_for_skill(skill, db_session)
        assert {user_a.id, user_b.id}.issubset(affected)

        delete_skill(skill_id=skill.id, db_session=db_session)
        db_session.commit()

        push_skills_for_users(affected, db_session)

        assert not (_skills_dir(ws_a) / skill.slug).exists()
        assert not (_skills_dir(ws_b) / skill.slug).exists()

    def test_one_failing_sandbox_does_not_abort_push_to_others(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        failing_sandbox_manager: Callable[..., StubSandboxManager],
        running_sandbox: Callable[..., SandboxHandle],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # We still need provisioned DB rows so get_sandbox_user_map returns
        # entries; the manager itself is stubbed out below.
        handle = running_sandbox()

        user_a = make_user(db_session)
        user_b = make_user(db_session)
        user_c = make_user(db_session)
        db_session.commit()
        _row_a, _ = _provision_with_status(handle, db_session, user_a)
        row_b, _ = _provision_with_status(handle, db_session, user_b)
        _row_c, _ = _provision_with_status(handle, db_session, user_c)

        # Make user_b's push fatally fail; the other two succeed silently.
        stub = failing_sandbox_manager(
            fail_on={row_b.id: FatalWriteError("Pod not found")}
        )

        # Redirect ALL get_sandbox_manager call sites to the stub.
        monkeypatch.setattr(
            "onyx.skills.push.get_sandbox_manager",
            lambda: stub,
        )

        # Public skill so all three users are affected.
        seeded_skill(
            slug=f"partial-{uuid4().hex[:6]}",
            public=True,
            bundle_files={"SKILL.md": "p\n"},
        )

        with caplog.at_level(logging.WARNING):
            # Must not raise even though one sandbox errors.
            push_skills_for_users({user_a.id, user_b.id, user_c.id}, db_session)

        # All three sandboxes were attempted (one failed, two succeeded).
        assert stub.write_files_to_sandbox_count == 3

        # A warning log line was emitted by either push.py (the aggregate
        # "partially failed" line) or base.py's push_to_sandboxes warning.
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "fail" in r.getMessage().lower() or "partial" in r.getMessage().lower()
            for r in warning_records
        ), f"Expected a partial-failure warning; got: {warning_records!r}"

    def test_user_with_overlapping_grants_receives_skill_exactly_once(
        self,
        db_session: Session,
        seeded_skill: Callable[..., Skill],
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        user = make_user(db_session)
        group_x = make_group(db_session, name=f"dup-x-{uuid4().hex[:6]}")
        group_y = make_group(db_session, name=f"dup-y-{uuid4().hex[:6]}")
        add_user_to_group(db_session, user, group_x)
        add_user_to_group(db_session, user, group_y)
        db_session.commit()

        _row, workspace = _provision_with_status(handle, db_session, user)

        skill = seeded_skill(
            slug=f"dup-grants-{uuid4().hex[:6]}",
            public=False,
            groups=[group_x, group_y],
            bundle_files={"SKILL.md": "dedup\n"},
        )

        push_skill_to_affected_sandboxes(skill, db_session)

        # Behavioural spec: the user sees the skill, exactly once — one file
        # at one path. (If anything along the pipeline ever attempted to
        # write twice, atomic-swap semantics would still leave exactly one
        # set of files on disk; that's the correct shape, and what we care
        # about. Set-level dedup of the resolver itself is pinned by
        # ``test_user_in_two_granted_groups_appears_once`` in
        # test_affected_users.py.)
        skill_dir = _skills_dir(workspace) / skill.slug
        skill_files = [p for p in skill_dir.rglob("*") if p.is_file()]
        assert len(skill_files) == 1
        assert skill_files[0].name == "SKILL.md"
        assert skill_files[0].read_bytes() == b"dedup\n"

    def test_company_search_skill_rendered_per_user(
        self,
        db_session: Session,
        fresh_registry: BuiltinSkillRegistry,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Per-user rendering: each user sees their own connector sources.

        Visibility is gated purely by the user-group → cc_pair grant. The
        cc_pairs are created with ``creator_id=None`` so the creator-id
        OR-branch in ``_add_user_filters`` cannot match either user — the
        rendered output differs strictly because their group memberships
        differ.
        """
        handle = running_sandbox()

        # Register only the company-search built-in (its real on-disk source).
        fresh_registry.register(
            slug="company-search",
            source_dir=Path(SKILLS_TEMPLATE_PATH) / "company-search",
        )

        user_a = make_user(db_session)
        user_b = make_user(db_session)

        # Each user belongs to their own group; cc_pairs are PRIVATE with
        # ``creator_id=None`` and mapped only to that group, so visibility
        # is per-user via the group join alone.
        group_a = make_group(db_session, name=f"cs-a-{uuid4().hex[:6]}")
        group_b = make_group(db_session, name=f"cs-b-{uuid4().hex[:6]}")
        add_user_to_group(db_session, user_a, group_a)
        add_user_to_group(db_session, user_b, group_b)
        db_session.commit()

        make_cc_pair(
            db_session,
            DocumentSource.SLACK,
            access_type=AccessType.PRIVATE,
            group=group_a,
        )
        make_cc_pair(
            db_session,
            DocumentSource.GOOGLE_DRIVE,
            access_type=AccessType.PRIVATE,
            group=group_b,
        )
        make_cc_pair(
            db_session,
            DocumentSource.LINEAR,
            access_type=AccessType.PRIVATE,
            group=group_b,
        )

        row_a, ws_a = _provision_with_status(handle, db_session, user_a)
        row_b, ws_b = _provision_with_status(handle, db_session, user_b)

        hydrate_sandbox_skills(sandbox_id=row_a.id, user=user_a, db_session=db_session)
        hydrate_sandbox_skills(sandbox_id=row_b.id, user=user_b, db_session=db_session)

        rendered_a = _skill_file_path(ws_a, "company-search").read_text()
        rendered_b = _skill_file_path(ws_b, "company-search").read_text()

        # The two users see different content (their own sources).
        assert rendered_a != rendered_b
        # A sees slack but not google_drive/linear.
        assert "slack" in rendered_a
        assert "google_drive" not in rendered_a
        assert "linear" not in rendered_a
        # B sees google_drive + linear but not slack.
        assert "google_drive" in rendered_b
        assert "linear" in rendered_b
        assert "slack" not in rendered_b

    def test_template_files_never_shipped(
        self,
        db_session: Session,
        tmp_path: Path,
        fresh_registry: BuiltinSkillRegistry,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()

        # Build a synthetic built-in skill source tree with a mix of files
        # the exclusion rule should keep IN and files it must keep OUT.
        slug = f"excl-builtin-{uuid4().hex[:6]}"
        source_dir = tmp_path / "builtin_src" / slug
        source_dir.mkdir(parents=True)

        # In: SKILL.md (required by the registry) + a vanilla script.
        (source_dir / "SKILL.md").write_text(
            f"---\nname: {slug}\ndescription: exclusion test\n---\n# body\n"
        )
        (source_dir / "script.py").write_text("print('hello')\n")

        # Out: template file (rendered separately), dotfile, __pycache__.
        (source_dir / "notes.template").write_text("templated stuff\n")
        (source_dir / ".hidden").write_text("secret\n")
        pycache = source_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "foo.pyc").write_bytes(b"\x00\x01")

        fresh_registry.register(slug=slug, source_dir=source_dir)

        user = make_user(db_session)
        db_session.commit()
        row, workspace = _provision_with_status(handle, db_session, user)

        hydrate_sandbox_skills(sandbox_id=row.id, user=user, db_session=db_session)

        skill_dir = _skills_dir(workspace) / slug
        names_present = {p.name for p in skill_dir.rglob("*") if p.is_file()}

        assert "SKILL.md" in names_present
        assert "script.py" in names_present
        assert "notes.template" not in names_present
        assert ".hidden" not in names_present
        assert "foo.pyc" not in names_present

        # And the __pycache__ subdir was never materialised.
        assert not (skill_dir / "__pycache__").exists()
