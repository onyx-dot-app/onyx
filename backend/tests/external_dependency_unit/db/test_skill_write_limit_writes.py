"""Every Skill write that can grow a user's Skills checks the per-user limit."""

import json
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.skill import resolve_skill_runtime_names, set_skill_enabled_for_user
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import api
from onyx.skills.ingest import prepare_skill_bundle
from onyx.skills.limits import (
    SKILL_WRITE_MAX_BYTES,
    SKILL_WRITE_MAX_FILES,
    SkillLimit,
    SkillLimitViolation,
)
from tests.external_dependency_unit.craft.db_helpers import (
    make_user,
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
