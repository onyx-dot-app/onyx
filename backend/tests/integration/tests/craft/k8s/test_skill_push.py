"""Skill API push tests in the Craft k8s integration lane."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillResponse
from onyx.server.features.skill.models import SkillUserShareRequest
from onyx.skills import built_in as built_in_module
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.push import build_skills_fileset_for_user
from onyx.skills.push import push_skill_to_affected_sandboxes
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup
from tests.integration.tests.craft.k8s.k8s_fixtures import SandboxHandle
from tests.integration.tests.craft.k8s.k8s_fixtures import WorkspaceProxy

pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
        reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
    ),
    pytest.mark.craft_skill_isolation,
]


def _skill_file_path(
    workspace: WorkspaceProxy, slug: str, name: str = "SKILL.md"
) -> WorkspaceProxy:
    return workspace / "managed" / "skills" / slug / name


def _skills_dir(workspace: WorkspaceProxy) -> WorkspaceProxy:
    return workspace / "managed" / "skills"


def _bundle(slug: str, body: bytes | str, **extra_files: bytes | str) -> bytes:
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            b"---\n"
            + f"name: {slug}\ndescription: {slug} integration test\n".encode("utf-8")
            + b"---\n"
            + body_bytes,
        )
        for path, content in extra_files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(path, data)
    return buf.getvalue()


def _create_skill(
    admin: DATestUser,
    slug: str,
    *,
    body: bytes | str,
    is_public: bool = False,
    group_ids: list[int] | None = None,
) -> SkillResponse:
    return SkillManager.create_custom(
        admin,
        slug=slug,
        is_public=is_public,
        group_ids=group_ids or [],
        bundle_bytes=_bundle(slug, body),
        filename=f"{slug}.zip",
    )


def _replace_bundle(
    admin: DATestUser,
    skill: SkillResponse,
    *,
    body: bytes | str,
) -> SkillResponse:
    return SkillManager.replace_bundle(
        skill,
        _bundle(skill.slug, body),
        admin,
    )


def _create_users(count: int) -> list[DATestUser]:
    prefix = f"craft-k8s-skill-{uuid4().hex[:8]}"
    return [UserManager.create(name=f"{prefix}-{idx}") for idx in range(count)]


@pytest.fixture
def user_group_factory(
    k8s_admin_user: DATestUser,
) -> Generator[Callable[[str, list[str]], DATestUserGroup], None, None]:
    groups: list[DATestUserGroup] = []

    def _create(name: str, user_ids: list[str]) -> DATestUserGroup:
        group = UserGroupManager.create(
            k8s_admin_user,
            name=name,
            user_ids=user_ids,
        )
        groups.append(group)
        return group

    try:
        yield _create
    finally:
        for group in reversed(groups):
            try:
                UserGroupManager.delete(group, k8s_admin_user)
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise


def _make_db_group(db_session: Session, name: str) -> UserGroup:
    group = UserGroup(name=name)
    db_session.add(group)
    db_session.flush()
    return group


def _add_user_to_group(db_session: Session, user: User, group: UserGroup) -> None:
    db_session.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
    db_session.flush()


def _make_private_cc_pair(
    db_session: Session,
    source: DocumentSource,
    group: UserGroup,
) -> ConnectorCredentialPair:
    suffix = uuid4().hex[:6]
    connector = Connector(
        name=f"cs-{source.value}-{suffix}",
        source=source,
        input_type=None,
        connector_specific_config={},
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=None, source=source)
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        name=f"cs-cc-{suffix}",
        connector_id=connector.id,
        credential_id=credential.id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PRIVATE,
        creator_id=None,
    )
    db_session.add(cc_pair)
    db_session.flush()
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id, cc_pair_id=cc_pair.id
        )
    )
    db_session.flush()
    return cc_pair


def _make_built_in_skill_row(db_session: Session, *, built_in_skill_id: str) -> Skill:
    skill = Skill(
        id=uuid4(),
        slug=built_in_skill_id,
        name=built_in_skill_id,
        description="test built-in",
        built_in_skill_id=built_in_skill_id,
        bundle_file_id=None,
        bundle_sha256=None,
        is_public=True,
        enabled=True,
    )
    db_session.add(skill)
    db_session.flush()
    return skill


def _reset_built_in_skill_row(db_session: Session, *, built_in_skill_id: str) -> Skill:
    from sqlalchemy import delete

    db_session.execute(delete(Skill).where(Skill.slug == built_in_skill_id))
    return _make_built_in_skill_row(db_session, built_in_skill_id=built_in_skill_id)


def _seed_custom_skill(
    db_session: Session,
    *,
    slug: str,
    public: bool,
    body: str,
    group: UserGroup | None = None,
) -> Skill:
    import hashlib

    from onyx.configs.constants import FileOrigin
    from onyx.db.models import Skill__UserGroup
    from onyx.file_store.file_store import get_default_file_store

    bundle_bytes = _bundle(slug, body)
    file_store = get_default_file_store()
    file_store.initialize()
    bundle_file_id = file_store.save_file(
        content=io.BytesIO(bundle_bytes),
        display_name=f"{slug}.zip",
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )
    skill = Skill(
        id=uuid4(),
        slug=slug,
        name=slug,
        description=f"Seeded skill {slug}",
        bundle_file_id=bundle_file_id,
        bundle_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        is_public=public,
        enabled=True,
    )
    db_session.add(skill)
    db_session.flush()
    if group is not None:
        db_session.add(Skill__UserGroup(skill_id=skill.id, user_group_id=group.id))
        db_session.flush()
    db_session.commit()
    db_session.refresh(skill)
    return skill


def _set_sandbox_status(
    db_session: Session, sandbox_id: UUID, status: SandboxStatus
) -> None:
    row = db_session.get(Sandbox, sandbox_id)
    assert row is not None
    row.status = status
    db_session.commit()


@pytest.fixture
def db_group_factory(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Callable[[str], UserGroup], None, None]:
    group_ids: list[int] = []

    def _create(name: str) -> UserGroup:
        group = _make_db_group(db_session, name)
        db_session.commit()
        db_session.refresh(group)
        group_ids.append(group.id)
        return group

    try:
        yield _create
    finally:
        db_session.rollback()
        ids = group_ids or [-1]
        # cc_pair links FK-reference the group; drop them before the group.
        db_session.query(UserGroup__ConnectorCredentialPair).filter(
            UserGroup__ConnectorCredentialPair.user_group_id.in_(ids)
        ).delete(synchronize_session=False)
        db_session.query(User__UserGroup).filter(
            User__UserGroup.user_group_id.in_(ids)
        ).delete(synchronize_session=False)
        for group_id in group_ids:
            row = db_session.get(UserGroup, group_id)
            if row is not None:
                db_session.delete(row)
        db_session.commit()


def _orm_user(db_session: Session, api_user: DATestUser) -> User:
    db_session.expire_all()
    row = db_session.get(User, UUID(api_user.id))
    assert row is not None, f"No User row for API user {api_user.id}"
    return row


def _api_sandbox_id(db_session: Session, api_user: DATestUser) -> UUID:
    db_session.expire_all()
    row = db_session.query(Sandbox).filter(Sandbox.user_id == UUID(api_user.id)).one()
    return row.id


def _rendered_company_search_lines(db_session: Session, user: User) -> list[str]:
    fileset = build_skills_fileset_for_user(user, db_session)
    return fileset["company-search/SKILL.md"].decode("utf-8").splitlines()


class TestSkillPush:
    def test_public_skill_lands_in_every_running_sandbox(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        users = _create_users(3)
        workspaces = handle.provision_api_users(users)

        slug = f"public-skill-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=True,
            body="public skill body\n",
        )

        for workspace in workspaces:
            _skill_file_path(workspace, skill.slug).wait_for_bytes(
                b"public skill body\n",
            )

    def test_private_skill_only_lands_in_shared_users_sandboxes(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
        user_group_factory: Callable[[str, list[str]], DATestUserGroup],
    ) -> None:
        handle = running_sandbox()
        user_a, user_b, user_c = _create_users(3)
        [ws_a, ws_b, ws_c] = handle.provision_api_users([user_a, user_b, user_c])
        group = user_group_factory(
            f"engineering-{uuid4().hex[:6]}",
            [user_a.id],
        )

        slug = f"eng-only-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=False,
            group_ids=[group.id],
            body="engineering only\n",
        )

        _skill_file_path(ws_a, skill.slug).wait_for_bytes(b"engineering only\n")
        _skill_file_path(ws_b, skill.slug).wait_for_absent()
        _skill_file_path(ws_c, skill.slug).wait_for_absent()

    def test_disable_skill_removes_files_from_affected_sandboxes(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
        user_group_factory: Callable[[str, list[str]], DATestUserGroup],
    ) -> None:
        handle = running_sandbox()
        [user] = _create_users(1)
        [workspace] = handle.provision_api_users([user])
        group = user_group_factory(
            f"disable-grp-{uuid4().hex[:6]}",
            [user.id],
        )

        slug = f"disable-me-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=False,
            group_ids=[group.id],
            body="to be disabled\n",
        )
        _skill_file_path(workspace, skill.slug).wait_for_bytes(b"to be disabled\n")

        SkillManager.patch_custom(
            skill, k8s_admin_user, SkillPatchRequest(enabled=False)
        )

        (_skills_dir(workspace) / skill.slug).wait_for_absent()

    def test_share_change_adds_to_newly_shared_and_removes_from_revoked(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
        user_group_factory: Callable[[str, list[str]], DATestUserGroup],
    ) -> None:
        handle = running_sandbox()
        user_a, user_b = _create_users(2)
        [ws_a, ws_b] = handle.provision_api_users([user_a, user_b])
        group_x = user_group_factory(
            f"grp-x-{uuid4().hex[:6]}",
            [user_a.id],
        )
        group_y = user_group_factory(
            f"grp-y-{uuid4().hex[:6]}",
            [user_b.id],
        )

        slug = f"shares-flip-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=False,
            group_ids=[group_x.id],
            body="shifting shares\n",
        )
        _skill_file_path(ws_a, skill.slug).wait_for_bytes(b"shifting shares\n")
        _skill_file_path(ws_b, skill.slug).wait_for_absent()

        SkillManager.replace_group_shares(skill, [group_y.id], k8s_admin_user)

        _skill_file_path(ws_a, skill.slug).wait_for_absent()
        _skill_file_path(ws_b, skill.slug).wait_for_bytes(b"shifting shares\n")

    def test_direct_user_share_change_adds_to_newly_shared_and_removes_from_revoked(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        user_a, user_b = _create_users(2)
        [ws_a, ws_b] = handle.provision_api_users([user_a, user_b])

        slug = f"direct-shares-flip-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=False,
            body="direct shifting shares\n",
        )
        _skill_file_path(ws_a, skill.slug).wait_for_absent()
        _skill_file_path(ws_b, skill.slug).wait_for_absent()

        skill = SkillManager.share(
            skill,
            k8s_admin_user,
            user_shares=[
                SkillUserShareRequest(
                    user_id=UUID(user_a.id),
                    permission=SkillSharePermission.VIEWER,
                )
            ],
        )
        assert [str(share.user.id) for share in skill.user_shares] == [user_a.id]
        _skill_file_path(ws_a, skill.slug).wait_for_bytes(b"direct shifting shares\n")
        _skill_file_path(ws_b, skill.slug).wait_for_absent()

        skill = SkillManager.share(
            skill,
            k8s_admin_user,
            user_shares=[
                SkillUserShareRequest(
                    user_id=UUID(user_b.id),
                    permission=SkillSharePermission.VIEWER,
                )
            ],
        )
        assert [str(share.user.id) for share in skill.user_shares] == [user_b.id]

        _skill_file_path(ws_a, skill.slug).wait_for_absent()
        _skill_file_path(ws_b, skill.slug).wait_for_bytes(b"direct shifting shares\n")

    def test_replace_bundle_propagates_new_content(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        [user] = _create_users(1)
        [workspace] = handle.provision_api_users([user])

        slug = f"versioned-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=True,
            body="version one\n",
        )
        _skill_file_path(workspace, skill.slug).wait_for_bytes(b"version one\n")

        _replace_bundle(k8s_admin_user, skill, body="version two\n")

        _skill_file_path(workspace, skill.slug).wait_for_bytes(b"version two\n")

    def test_delete_skill_removes_directory_from_all_affected_sandboxes(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        user_a, user_b = _create_users(2)
        [ws_a, ws_b] = handle.provision_api_users([user_a, user_b])

        slug = f"to-delete-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=True,
            body="will be deleted\n",
        )
        _skill_file_path(ws_a, skill.slug).wait_for_bytes(b"will be deleted\n")
        _skill_file_path(ws_b, skill.slug).wait_for_bytes(b"will be deleted\n")

        SkillManager.delete_custom(skill, k8s_admin_user)

        (_skills_dir(ws_a) / skill.slug).wait_for_absent()
        (_skills_dir(ws_b) / skill.slug).wait_for_absent()

    def test_user_with_overlapping_shares_receives_skill_once(
        self,
        k8s_admin_user: DATestUser,
        running_sandbox: Callable[..., SandboxHandle],
        user_group_factory: Callable[[str, list[str]], DATestUserGroup],
    ) -> None:
        handle = running_sandbox()
        [user] = _create_users(1)
        [workspace] = handle.provision_api_users([user])
        group_x = user_group_factory(
            f"dup-x-{uuid4().hex[:6]}",
            [user.id],
        )
        group_y = user_group_factory(
            f"dup-y-{uuid4().hex[:6]}",
            [user.id],
        )

        slug = f"dup-shares-{uuid4().hex[:6]}"
        skill = _create_skill(
            k8s_admin_user,
            slug,
            is_public=False,
            group_ids=[group_x.id, group_y.id],
            body="dedup\n",
        )

        _skill_file_path(workspace, skill.slug).wait_for_bytes(b"dedup\n")
        skill_dir = _skills_dir(workspace) / skill.slug
        skill_files = [p for p in skill_dir.rglob("*") if p.is_file()]
        assert len(skill_files) == 1
        assert skill_files[0].name == "SKILL.md"


class TestSkillPushLowLevel:
    """Push/hydrate behaviours that need control the admin API does not expose."""

    def test_push_skips_sleeping_sandboxes(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        [api_user] = _create_users(1)
        [workspace] = handle.provision_api_users([api_user])

        _set_sandbox_status(
            db_session, _api_sandbox_id(db_session, api_user), SandboxStatus.SLEEPING
        )

        skill = _seed_custom_skill(
            db_session,
            slug=f"sleeping-{uuid4().hex[:6]}",
            public=True,
            body="anything\n",
        )

        push_skill_to_affected_sandboxes(skill, db_session)

        assert workspace.exists()
        assert not (_skills_dir(workspace) / skill.slug).exists()

    def test_push_skips_terminated_sandboxes(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        handle = running_sandbox()
        [api_user] = _create_users(1)
        [workspace] = handle.provision_api_users([api_user])

        _set_sandbox_status(
            db_session, _api_sandbox_id(db_session, api_user), SandboxStatus.TERMINATED
        )

        skill = _seed_custom_skill(
            db_session,
            slug=f"terminated-{uuid4().hex[:6]}",
            public=True,
            body="anything\n",
        )

        push_skill_to_affected_sandboxes(skill, db_session)

        assert workspace.exists()
        assert not (_skills_dir(workspace) / skill.slug).exists()

    def test_company_search_skill_rendered_per_user(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        db_group_factory: Callable[[str], UserGroup],
    ) -> None:
        _reset_built_in_skill_row(db_session, built_in_skill_id="company-search")
        db_session.commit()

        api_user_a, api_user_b = _create_users(2)
        user_a = _orm_user(db_session, api_user_a)
        user_b = _orm_user(db_session, api_user_b)

        group_a = db_group_factory(f"cs-a-{uuid4().hex[:6]}")
        group_b = db_group_factory(f"cs-b-{uuid4().hex[:6]}")
        _add_user_to_group(db_session, user_a, group_a)
        _add_user_to_group(db_session, user_b, group_b)
        db_session.commit()

        baseline_a = set(_rendered_company_search_lines(db_session, user_a))
        baseline_b = set(_rendered_company_search_lines(db_session, user_b))

        _make_private_cc_pair(db_session, DocumentSource.SLACK, group_a)
        _make_private_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE, group_b)
        db_session.commit()

        after_a = set(_rendered_company_search_lines(db_session, user_a))
        after_b = set(_rendered_company_search_lines(db_session, user_b))

        # Diff against baseline to cancel out PUBLIC cc_pairs leaked by other tests.
        gained_a = after_a - baseline_a
        gained_b = after_b - baseline_b

        assert any("slack" in line for line in gained_a)
        assert not any("google_drive" in line for line in gained_a)

        assert any("google_drive" in line for line in gained_b)
        assert not any("slack" in line for line in gained_b)

    def test_template_files_never_shipped(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slug = f"excl-builtin-{uuid4().hex[:6]}"
        skills_root = tmp_path / "builtin_src"
        source_dir = skills_root / slug
        source_dir.mkdir(parents=True)

        # Files the exclusion rule must keep IN.
        (source_dir / "SKILL.md").write_text(
            f"---\nname: {slug}\ndescription: exclusion test\n---\n# body\n"
        )
        (source_dir / "script.py").write_text("print('hello')\n")

        # Files the exclusion rule must keep OUT.
        (source_dir / "notes.template").write_text("templated stuff\n")
        (source_dir / ".hidden").write_text("secret\n")
        pycache = source_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "foo.pyc").write_bytes(b"\x00\x01")

        monkeypatch.setattr(built_in_module, "BUILTIN_SKILLS_PATH", skills_root)
        monkeypatch.setitem(
            built_in_module.BUILT_IN_SKILLS,
            slug,
            BuiltInSkillDefinition(built_in_skill_id=slug),
        )
        _make_built_in_skill_row(db_session, built_in_skill_id=slug)

        [api_user] = _create_users(1)
        user = _orm_user(db_session, api_user)
        db_session.commit()

        fileset = build_skills_fileset_for_user(user, db_session)
        shipped = {Path(rel).name for rel in fileset if rel.startswith(f"{slug}/")}

        assert "SKILL.md" in shipped
        assert "script.py" in shipped
        assert "notes.template" not in shipped
        assert ".hidden" not in shipped
        assert "foo.pyc" not in shipped
        assert not any(rel.startswith(f"{slug}/__pycache__/") for rel in fileset)
