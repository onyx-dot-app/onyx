import io
import zipfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ee.onyx.db import user_group as user_group_db
from ee.onyx.db.user_group import fetch_user_group_member_ids
from ee.onyx.server.user_group import api as user_group_api
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import User, UserSkillPreference
from onyx.db.skill import (
    SkillManagementPolicy,
    list_runtime_skills_for_user,
    list_skills,
    resolve_skill_installation_policies,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.db.users import lock_group_membership
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.file_store.file_store import FileStore
from onyx.server.features.build.sandbox.models import FileSet, PushResult
from onyx.skills import push
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_sandbox,
    make_skill,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest.mark.parametrize(
    ("in_a", "in_b", "b_policy", "expected"),
    [
        (True, False, None, Policy.NOT_AVAILABLE),
        (False, True, None, Policy.REQUIRED),
        (True, True, None, Policy.REQUIRED),
        (False, False, None, Policy.REQUIRED),
        (True, True, Policy.AVAILABLE, Policy.AVAILABLE),
    ],
)
def test_group_policy_truth_table(
    db_session: Session,
    in_a: bool,
    in_b: bool,
    b_policy: Policy | None,
    expected: Policy,
) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    skill.installation_policy = Policy.REQUIRED
    a, b = make_group(db_session), make_group(db_session)
    share_skill_with_group(
        db_session, skill, a
    ).installation_policy = Policy.NOT_AVAILABLE
    share_skill_with_group(db_session, skill, b).installation_policy = b_policy
    if in_a:
        add_user_to_group(db_session, user, a)
    if in_b:
        add_user_to_group(db_session, user, b)
    db_session.flush()

    assert resolve_skill_installation_policies([user.id], [skill.id], db_session) == {
        (user.id, skill.id): expected
    }
    listed = list_skills(
        policy=SkillManagementPolicy.VIEW, user=user, db_session=db_session
    )
    assert (skill.id in {row.id for row in listed}) is (
        expected != Policy.NOT_AVAILABLE
    )
    state = skill_user_states(user, [skill.id], db_session)[skill.id]
    assert state.enabled is (expected == Policy.REQUIRED)
    assert state.can_toggle is (expected == Policy.AVAILABLE)
    runtime = list_runtime_skills_for_user(user=user, db_session=db_session)
    assert (skill.id in {row.id for row in runtime}) is (expected == Policy.REQUIRED)


@pytest.mark.parametrize("company", list(Policy))
@pytest.mark.parametrize("override", [None, *Policy])
def test_one_group_overrides_company_or_inherits(
    db_session: Session, company: Policy, override: Policy | None
) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    skill.installation_policy = company
    group = make_group(db_session)
    add_user_to_group(db_session, user, group)
    share_skill_with_group(db_session, skill, group).installation_policy = override
    db_session.flush()

    assert resolve_skill_installation_policies([user.id], [skill.id], db_session) == {
        (user.id, skill.id): override or company
    }


@pytest.mark.parametrize("first", list(Policy))
@pytest.mark.parametrize("second", list(Policy))
def test_most_open_applicable_group_wins(
    db_session: Session, first: Policy, second: Policy
) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    for setting in (first, second):
        group = make_group(db_session)
        add_user_to_group(db_session, user, group)
        share_skill_with_group(db_session, skill, group).installation_policy = setting
    db_session.flush()
    ordered = [Policy.NOT_AVAILABLE, Policy.AVAILABLE, Policy.DEFAULT, Policy.REQUIRED]
    expected = max((first, second), key=ordered.index)
    assert resolve_skill_installation_policies([user.id], [skill.id], db_session) == {
        (user.id, skill.id): expected
    }


@pytest.mark.parametrize("saved_enabled", [False, True])
def test_policy_changes_preserve_personal_choice(
    db_session: Session, saved_enabled: bool
) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    skill.installation_policy = Policy.DEFAULT
    group = make_group(db_session)
    add_user_to_group(db_session, user, group)
    share = share_skill_with_group(db_session, skill, group)
    preference = UserSkillPreference(
        user_id=user.id, skill_id=skill.id, name=skill.name, enabled=saved_enabled
    )
    db_session.add(preference)
    for setting, enabled, can_toggle in [
        (Policy.REQUIRED, True, False),
        (Policy.NOT_AVAILABLE, False, False),
        (None, saved_enabled, True),
    ]:
        share.installation_policy = setting
        db_session.flush()
        state = skill_user_states(user, [skill.id], db_session)[skill.id]
        assert (state.enabled, state.can_toggle) == (enabled, can_toggle)
        runtime = list_runtime_skills_for_user(user=user, db_session=db_session)
        assert (skill.id in {row.id for row in runtime}) is enabled
        db_session.refresh(preference)
        assert preference.enabled is saved_enabled


@pytest.mark.parametrize("access", ["owner", "direct", "group", "public"])
def test_not_available_keeps_only_owner_and_direct_visibility(
    db_session: Session, access: str
) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(
        db_session,
        is_public=access == "public",
        author_user_id=user.id if access == "owner" else None,
    )
    skill.installation_policy = Policy.NOT_AVAILABLE
    if access == "direct":
        share_skill_with_user(db_session, skill, user)
    if access == "group":
        group = make_group(db_session)
        add_user_to_group(db_session, user, group)
        share_skill_with_group(db_session, skill, group)
    db_session.flush()

    listed = list_skills(
        policy=SkillManagementPolicy.VIEW, user=user, db_session=db_session
    )
    assert (skill.id in {row.id for row in listed}) is (access in {"owner", "direct"})
    state = skill_user_states(user, [skill.id], db_session)[skill.id]
    assert not state.enabled
    assert not state.can_toggle
    runtime = list_runtime_skills_for_user(user=user, db_session=db_session)
    assert skill.id not in {row.id for row in runtime}


def test_batch_resolves_all_pairs_in_one_query_and_omits_retired(
    db_session: Session,
) -> None:
    users = [make_user(db_session, standard_account=True) for _ in range(3)]
    skills = [make_skill(db_session, is_public=True) for _ in range(3)]
    skills[0].installation_policy = Policy.DEFAULT
    skills[1].retired_at = datetime.now(timezone.utc)
    group = make_group(db_session)
    add_user_to_group(db_session, users[0], group)
    share_skill_with_group(
        db_session, skills[0], group
    ).installation_policy = Policy.REQUIRED
    db_session.flush()

    with patch.object(db_session, "execute", wraps=db_session.execute) as execute:
        resolved = resolve_skill_installation_policies(
            [user.id for user in users], [skill.id for skill in skills], db_session
        )
    assert execute.call_count == 1
    assert resolved == {
        **{(user.id, skills[2].id): Policy.AVAILABLE for user in users},
        (users[0].id, skills[0].id): Policy.REQUIRED,
        (users[1].id, skills[0].id): Policy.DEFAULT,
        (users[2].id, skills[0].id): Policy.DEFAULT,
    }
    assert resolve_skill_installation_policies([], [skills[0].id], db_session) == {}
    assert resolve_skill_installation_policies([users[0].id], [], db_session) == {}
    assert skills[1].id not in skill_user_states(users[0], [skills[1].id], db_session)


def test_unavailable_selection_does_not_block_another_skill(
    db_session: Session,
) -> None:
    user = make_user(db_session, standard_account=True)
    blocked = make_skill(db_session, author_user_id=user.id)
    set_skill_enabled_for_user(
        skill_id=blocked.id, enabled=True, user=user, db_session=db_session
    )
    group = make_group(db_session)
    add_user_to_group(db_session, user, group)
    share_skill_with_group(
        db_session, blocked, group
    ).installation_policy = Policy.NOT_AVAILABLE
    default = make_skill(db_session, name=blocked.name, is_public=True)
    default.installation_policy = Policy.DEFAULT
    db_session.flush()
    states = skill_user_states(user, [blocked.id, default.id], db_session)
    assert not states[blocked.id].enabled
    assert states[default.id].enabled
    preference = db_session.get(UserSkillPreference, (user.id, blocked.id))
    assert preference is not None and preference.enabled

    set_skill_enabled_for_user(
        skill_id=default.id, enabled=True, user=user, db_session=db_session
    )
    db_session.refresh(preference)
    assert not preference.enabled
    assert skill_user_states(user, [default.id], db_session)[default.id].enabled


@pytest.mark.usefixtures("enable_ee")
def test_membership_changes_push_group_skills_after_commit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = make_user(db_session, is_admin=True)
    joiner = make_user(db_session, standard_account=True)
    stayer = make_user(db_session, standard_account=True)
    group = make_group(db_session)
    group.is_up_to_date = True
    add_user_to_group(db_session, stayer, group)
    sandboxes = {make_sandbox(db_session, u).id: u.id for u in (joiner, stayer)}
    skill = make_skill(db_session, is_public=True)
    skill.installation_policy = Policy.AVAILABLE
    assert skill.current_version is not None
    skill.current_version.is_valid = True
    share = share_skill_with_group(db_session, skill, group)
    share.installation_policy = Policy.REQUIRED
    db_session.commit()

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SKILL.md", f"---\nname: {skill.name}\n---\n")
    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = lambda *_, **__: io.BytesIO(output.getvalue())
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    pushed: list[tuple[UUID, bool, set[UUID]]] = []

    class Manager:
        def push_to_sandboxes(
            self, *, mount_path: str, sandbox_files: dict[UUID, FileSet]
        ) -> PushResult:
            for sandbox_id, files in sandbox_files.items():
                self.push_to_sandbox(
                    sandbox_id=sandbox_id, mount_path=mount_path, files=files
                )
            count = len(sandbox_files)
            return PushResult(targets=count, succeeded=count, failures=[])

        def push_to_sandbox(
            self, *, sandbox_id: UUID, mount_path: str, files: FileSet
        ) -> PushResult:
            del mount_path
            with get_session_with_current_tenant() as other:
                # Raises if the request still holds the membership lock.
                lock_group_membership(other, nowait=True)
                members = fetch_user_group_member_ids(other, group.id)
                other.rollback()
            delivered = f"{skill.name}/SKILL.md" in files
            pushed.append((sandboxes[sandbox_id], delivered, members))
            return PushResult(targets=1, succeeded=1, failures=[])

    monkeypatch.setattr(push, "get_sandbox_manager", lambda: Manager())
    # Deletion is finished later by the sync task, as in the default deployment.
    monkeypatch.setattr(user_group_api, "DISABLE_VECTOR_DB", False)
    app = FastAPI()
    app.include_router(user_group_api.router)
    register_onyx_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    path = f"/manage/admin/user-group/{group.id}"

    response = client.post(f"{path}/add-users", json={"user_ids": [str(joiner.id)]})
    assert response.status_code == 200, response.text
    # Only the joiner's Skills changed, and the push saw the committed roster.
    assert pushed == [(joiner.id, True, {joiner.id, stayer.id})]

    pushed.clear()
    response = client.patch(path, json={"user_ids": [str(stayer.id)]})
    assert response.status_code == 200, response.text
    assert pushed == [(joiner.id, False, {stayer.id})]

    # Another request adds the user immediately before this mutation gets its lock.
    # Capture must follow the lock, or the later removal misses this recipient.
    interleaved = False

    def lock_after_add(session: Session, *, nowait: bool = False) -> None:
        nonlocal interleaved
        if session is db_session and not interleaved:
            interleaved = True
            with get_session_with_current_tenant() as other:
                user_group_api.add_users(
                    group.id,
                    user_group_api.AddUsersToUserGroupRequest(user_ids=[joiner.id]),
                    other.get_one(User, admin.id),
                    other,
                )
        lock_group_membership(session, nowait=nowait)

    monkeypatch.setattr(
        user_group_api, "lock_group_membership", lock_after_add, raising=False
    )
    monkeypatch.setattr(user_group_db, "lock_group_membership", lock_after_add)
    pushed.clear()
    response = client.patch(path, json={"user_ids": [str(stayer.id)]})
    assert response.status_code == 200, response.text
    assert pushed == [
        (joiner.id, True, {joiner.id, stayer.id}),
        (joiner.id, False, {stayer.id}),
    ]

    # Even an already-present add must release its lock before the refresh helper.
    original_push = user_group_api.push_skills_for_users

    def unlocked_push(user_ids: set[UUID], session: Session) -> None:
        with get_session_with_current_tenant() as other:
            lock_group_membership(other, nowait=True)
            other.rollback()
        original_push(user_ids, session)

    monkeypatch.setattr(user_group_api, "push_skills_for_users", unlocked_push)
    response = client.post(f"{path}/add-users", json={"user_ids": [str(stayer.id)]})
    assert response.status_code == 200, response.text

    pushed.clear()
    response = client.delete(path)
    assert response.status_code == 200, response.text
    assert pushed == [(stayer.id, False, set())]
