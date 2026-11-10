"""Every Skill write that can grow a user's Skills checks the per-user limit."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill, Skill__UserGroup, User
from onyx.db.resource_access import ResourceAccessChange, mutate_resource_access
from onyx.db.skill import (
    SkillAccessAdapter,
    resolve_skill_runtime_names,
    set_skill_enabled_for_user,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import api
from onyx.skills.ingest import prepare_skill_bundle
from onyx.skills.limits import (
    SKILL_WRITE_MAX_BYTES,
    SKILL_WRITE_MAX_FILES,
    SkillLimit,
    SkillLimitViolation,
)
from tests.external_dependency_unit.conftest import delete_test_user
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_user,
    share_skill_with_group,
    share_skill_with_user,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    upload,
)
from tests.external_dependency_unit.db.test_skill_write_limit import MIB, sized_skill
from tests.external_dependency_unit.db.test_skill_write_limit import clean as clean

pytestmark = pytest.mark.usefixtures(
    "tenant_context", "enable_ee", "initialize_file_store"
)
REQUEST = Request({"type": "http"})


def _skill_limit(error: OnyxError) -> SkillLimitViolation:
    assert error.status_code == 413
    assert error.extra is not None
    return SkillLimitViolation.model_validate(error.extra["skill_limit"])


@pytest.mark.parametrize("over", [None, "bytes", "files"])
def test_upload_at_exact_limit(clean: Session, over: str | None) -> None:
    user = make_user(clean, standard_account=True)
    name = f"limit-upload-{uuid4().hex[:8]}"
    content = bundle(name)
    metadata = prepare_skill_bundle(content, "skill.zip").metadata
    sized_skill(
        clean,
        size=SKILL_WRITE_MAX_BYTES - metadata.unpacked_size_bytes + (over == "bytes"),
        files=SKILL_WRITE_MAX_FILES - metadata.file_count + (over == "files"),
        author=user,
    )

    if over is None:
        assert api.create_custom_skill(
            upload(content), True, user, clean, http_request=REQUEST
        ).enabled
        return
    with pytest.raises(OnyxError) as refused:
        api.create_custom_skill(
            upload(content), True, user, clean, http_request=REQUEST
        )
    limit = _skill_limit(refused.value)
    assert limit.failed_limit == over
    assert limit.affected_user_count == 1
    assert limit.usage is not None
    assert limit.usage.bytes == SKILL_WRITE_MAX_BYTES + (over == "bytes")
    assert limit.usage.files == SKILL_WRITE_MAX_FILES + (over == "files")
    assert clean.scalar(select(Skill.id).where(Skill.name == name)) is None


def test_batch_import_refuses_only_the_bundle_over_the_limit(clean: Session) -> None:
    user = make_user(clean, standard_account=True)
    sized_skill(clean, size=SKILL_WRITE_MAX_BYTES, author=user)
    small = f"limit-a-{uuid4().hex[:8]}"
    response = api.create_custom_skills_batch(
        [upload(bundle(small))],
        True,
        None,
        user,
        clean,
        http_request=REQUEST,
    )
    assert response.imported == []
    assert len(response.not_imported) == 1
    assert "limit" in response.not_imported[0].reason
    # Without auto-enable the upload adds nothing the user gets.
    response = api.create_custom_skills_batch(
        [upload(bundle(small))], False, None, user, clean, http_request=REQUEST
    )
    assert [item.skill.name for item in response.imported] == [small]


def test_larger_edit_is_refused_and_keeps_the_version(clean: Session) -> None:
    user = make_user(clean, standard_account=True)
    name = f"limit-edit-{uuid4().hex[:8]}"
    created = api.create_custom_skill(
        upload(bundle(name)), True, user, clean, http_request=REQUEST
    )
    larger = bundle(name, "Longer instructions " * 200)
    metadata = prepare_skill_bundle(larger, "skill.zip").metadata
    sized_skill(
        clean,
        size=SKILL_WRITE_MAX_BYTES - metadata.unpacked_size_bytes + 1,
        author=user,
    )
    clean.commit()
    skill = clean.get(Skill, created.id)
    assert skill is not None
    version_id = skill.current_version_id

    with pytest.raises(OnyxError) as refused:
        api.replace_current_user_skill_bundle(
            created.id, upload(larger), user, clean, http_request=REQUEST
        )

    assert _skill_limit(refused.value).failed_limit == SkillLimit.BYTES
    clean.expire_all()
    skill = clean.get(Skill, created.id)
    assert skill is not None and skill.current_version_id == version_id


def _group_policies(session: Session, skill_id: UUID) -> dict[int, Policy | None]:
    return dict(
        session.execute(
            select(
                Skill__UserGroup.user_group_id, Skill__UserGroup.installation_policy
            ).where(Skill__UserGroup.skill_id == skill_id)
        )
        .tuples()
        .all()
    )


def test_required_group_change_refused_for_one_over_member(clean: Session) -> None:
    admin, _ = manager(clean, global_access=True)
    over, under, also_under = (
        make_user(clean, standard_account=True) for _ in range(3)
    )
    group = make_group(clean)
    for user in (over, under, also_under):
        add_user_to_group(clean, user, group)
    sized_skill(clean, size=SKILL_WRITE_MAX_BYTES - MIB, author=over)
    target = sized_skill(clean, size=2 * MIB, author=admin, policy=Policy.AVAILABLE)
    share_skill_with_group(clean, target, group)

    def set_group_policy(policy: Policy) -> None:
        mutate_resource_access(
            [target.id],
            ResourceAccessChange(group_installation_policies={group.id: policy}),
            admin,
            clean,
            SkillAccessAdapter(),
        )

    with pytest.raises(OnyxError) as refused:
        set_group_policy(Policy.REQUIRED)
    limit = _skill_limit(refused.value)
    assert limit.affected_user_count == 1 and limit.usage is None
    assert "1 user past" in refused.value.detail
    assert _group_policies(clean, target.id) == {group.id: None}

    # Available grants nothing until a user turns the skill on.
    set_group_policy(Policy.AVAILABLE)
    assert _group_policies(clean, target.id) == {group.id: Policy.AVAILABLE}


def test_bulk_share_fails_only_the_skill_over_the_limit(clean: Session) -> None:
    admin, _ = manager(clean, global_access=True)
    member = make_user(clean, standard_account=True)
    group = make_group(clean)
    add_user_to_group(clean, member, group)
    sized_skill(clean, size=SKILL_WRITE_MAX_BYTES - MIB, author=member)
    fits = sized_skill(clean, size=MIB // 2, author=admin, policy=Policy.AVAILABLE)
    too_big = sized_skill(clean, size=2 * MIB, author=admin, policy=Policy.AVAILABLE)

    result = mutate_resource_access(
        [fits.id, too_big.id],
        ResourceAccessChange(
            group_shares={group.id: SkillSharePermission.VIEWER},
            group_installation_policies={group.id: Policy.REQUIRED},
        ),
        admin,
        clean,
        SkillAccessAdapter(),
        add_only=True,
        allow_partial=True,
    )

    assert result.succeeded == [fits.id]
    assert set(result.failed) == {too_big.id}
    assert "1 user past" in result.failed[too_big.id].detail
    assert _group_policies(clean, too_big.id) == {}


def test_user_already_over_may_reduce_but_not_grow(clean: Session) -> None:
    user = make_user(clean, standard_account=True)
    owner = make_user(clean, standard_account=True)
    shared = [
        sized_skill(clean, size=300 * MIB, author=owner, policy=Policy.DEFAULT)
        for _ in range(3)
    ]
    for skill in shared:
        share_skill_with_user(clean, skill, user)
    added = sized_skill(clean, size=MIB, author=owner, policy=Policy.AVAILABLE)
    share_skill_with_user(clean, added, user)

    set_skill_enabled_for_user(
        skill_id=shared[0].id, enabled=False, user=user, db_session=clean
    )
    with pytest.raises(OnyxError) as refused:
        set_skill_enabled_for_user(
            skill_id=added.id, enabled=True, user=user, db_session=clean
        )
    usage = _skill_limit(refused.value).usage
    assert usage is not None and usage.bytes == 601 * MIB


def _delete(skill_ids: list[UUID], users: list[User]) -> None:
    with get_session_with_current_tenant() as cleanup:
        cleanup.execute(delete(Skill).where(Skill.id.in_(skill_ids)))
        delete_test_user(cleanup, *users)
        cleanup.commit()


def test_concurrent_admin_changes_refuse_one(db_session: Session) -> None:
    admin = make_user(db_session, is_admin=True)
    target, owner = (make_user(db_session, standard_account=True) for _ in range(2))
    skills = [
        sized_skill(db_session, size=300 * MIB, author=owner, policy=Policy.AVAILABLE)
        for _ in range(2)
    ]
    for skill in skills:
        share_skill_with_user(db_session, skill, target)
    skill_ids = [skill.id for skill in skills]
    db_session.commit()
    start = Barrier(2)

    def require(skill_id: UUID) -> OnyxError | None:
        with get_session_with_current_tenant() as writer:
            actor = writer.get(User, admin.id)
            assert actor is not None
            start.wait()
            try:
                mutate_resource_access(
                    [skill_id],
                    ResourceAccessChange(installation_policy=Policy.REQUIRED),
                    actor,
                    writer,
                    SkillAccessAdapter(),
                )
            except OnyxError as exc:
                writer.rollback()
                return exc
            writer.commit()
            return None

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(require, skill_ids))
        refused = [result for result in results if result is not None]
        assert len(refused) == 1
        assert _skill_limit(refused[0]).affected_user_count == 2
        db_session.expire_all()
        policies = db_session.scalars(
            select(Skill.installation_policy).where(Skill.id.in_(skill_ids))
        ).all()
        assert sorted(policies) == sorted([Policy.AVAILABLE, Policy.REQUIRED])
    finally:
        _delete(skill_ids, [admin, target, owner])


@pytest.mark.parametrize("action", ["share", "enable"])
def test_bulk_response_preserves_structured_limit(clean: Session, action: str) -> None:
    actor, _ = manager(clean, global_access=True)
    sized_skill(clean, size=SKILL_WRITE_MAX_BYTES, author=actor)
    target = sized_skill(clean, size=MIB, author=actor, policy=Policy.AVAILABLE)
    request = (
        api.SkillBulkShareRequest(
            action="share",
            skill_ids=[target.id],
            sharing=api.SkillShareRequest(installation_policy=Policy.REQUIRED),
        )
        if action == "share"
        else api.SkillBulkActionRequest(action="enable", skill_ids=[target.id])
    )

    response = api.bulk_update_skills(request, actor, clean, http_request=REQUEST)

    assert response.succeeded == []
    failure = response.failed[0]
    assert failure.skill_id == target.id
    assert failure.skill_limit is not None
    assert failure.skill_limit.failed_limit == SkillLimit.BYTES
    assert failure.skill_limit.affected_user_count == 1
    assert failure.skill_limit.usage is not None
    assert failure.skill_limit.usage.charged_bytes == SKILL_WRITE_MAX_BYTES + MIB
    assert target.installation_policy == Policy.AVAILABLE


@pytest.mark.parametrize("policy", [Policy.DEFAULT, Policy.REQUIRED])
@pytest.mark.parametrize("over", [None, "bytes", "files"])
@pytest.mark.parametrize("auto_enable", [True, False])
@pytest.mark.parametrize("actor_over", [True, False])
def test_shared_creation(
    clean: Session,
    policy: Policy,
    over: str | None,
    auto_enable: bool,
    actor_over: bool,
) -> None:
    admin, _ = manager(clean, global_access=True)
    member = make_user(clean, standard_account=True)
    name = "budget-upload-" + uuid4().hex[:8]
    content = bundle(name)
    metadata = prepare_skill_bundle(content, "skill.zip").metadata
    sized_skill(
        clean,
        size=SKILL_WRITE_MAX_BYTES - metadata.unpacked_size_bytes + (over == "bytes"),
        files=SKILL_WRITE_MAX_FILES - metadata.file_count + (over == "files"),
        author=admin if actor_over else member,
    )
    clean.commit()
    result = api.create_custom_skills_batch(
        [upload(content)],
        auto_enable,
        json.dumps(
            {
                "public_permission": SkillSharePermission.VIEWER.value,
                "installation_policy": policy.value,
            }
        ),
        admin,
        clean,
        http_request=Request({"type": "http"}),
    )
    if over is None:
        assert len(result.imported) == 1, result
        assert (
            clean.scalar(select(Skill.id).where(Skill.name == name))
            in resolve_skill_runtime_names(member, clean).values()
        )
    else:
        assert not result.imported, result
        assert (
            len(result.not_imported) == 1 and "limit" in result.not_imported[0].reason
        )
        assert clean.scalar(select(Skill.id).where(Skill.name == name)) is None
