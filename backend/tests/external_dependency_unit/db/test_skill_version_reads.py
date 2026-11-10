"""Reader cutover with real PostgreSQL rows and FileStore bundles."""

from uuid import uuid4

import pytest
from fastapi import Request
from scripts.check_skill_version_cutover import check_cutover
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.skill_versions.tasks import (
    PROGRESS_KEY,
    repair_skill_versions,
)
from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Skill, SkillVersion, User
from onyx.db.skill import (
    SkillValidityUpdate,
    list_runtime_skills_for_user,
    persist_skill_validity,
    skill_user_states,
)
from onyx.db.skill_version import skill_version_repair_batch
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.server.features.skill import api
from onyx.server.features.skill.models import SkillResponse
from onyx.skills.content import read_custom_skill_bundle_instructions
from onyx.skills.push import _assemble_fileset
from onyx.skills.validation import validate_stored_custom_skill
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    upload,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    tenant as tenant,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    user as user,
)


def test_readers_ignore_legacy_bundle_and_validity(
    session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("current-reader")),
        True,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    skill.bundle_file_id = "obsolete-legacy-file"
    skill.bundle_sha256 = "f" * 64
    skill.is_valid = False
    session.commit()
    assert "First instructions" in read_custom_skill_bundle_instructions(skill)
    assert (
        validate_stored_custom_skill(skill, get_default_file_store()).is_valid is True
    )
    assert (
        SkillResponse.from_custom(
            skill,
            enabled=True,
            effective_installation_policy=SkillInstallationPolicy.AVAILABLE,
        ).is_valid
        is True
    )
    assert skill_user_states(user, [skill.id], session)[skill.id].can_toggle
    assert skill.id in {
        row.id for row in list_runtime_skills_for_user(db_session=session, user=user)
    }
    assert "current-reader/SKILL.md" in _assemble_fileset([skill], user, session)


def test_current_invalid_blocks_runtime_even_when_legacy_valid(
    session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("invalid-reader")),
        True,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    version = session.get(SkillVersion, skill.current_version_id)
    assert version is not None
    version.is_valid = False
    session.commit()
    assert (
        SkillResponse.from_custom(
            skill,
            enabled=True,
            effective_installation_policy=SkillInstallationPolicy.AVAILABLE,
        ).is_valid
        is False
    )
    assert not skill_user_states(user, [skill.id], session)[skill.id].can_toggle
    assert skill.id not in {
        row.id for row in list_runtime_skills_for_user(db_session=session, user=user)
    }
    assert _assemble_fileset([skill], user, session) == {}


def test_pointerless_skill_never_falls_back_to_legacy(
    session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("pointerless-reader")),
        True,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    skill.current_version_id = None
    session.commit()
    session.expire_all()
    with pytest.raises(OnyxError):
        read_custom_skill_bundle_instructions(skill)
    assert (
        validate_stored_custom_skill(skill, get_default_file_store()).is_valid is False
    )
    assert _assemble_fileset([skill], user, session) == {}
    assert not skill_user_states(user, [skill.id], session)[skill.id].can_toggle


def test_backfilled_equal_ids_and_builtin_outer_join(
    session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("backfilled-reader")),
        True,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    version = session.get(SkillVersion, skill.current_version_id)
    assert version is not None
    version.id = skill.id
    skill.current_version_id = skill.id
    builtin = Skill(
        id=uuid4(),
        name="pptx",
        description="Built in",
        built_in_skill_id="pptx",
        public_permission=SkillSharePermission.VIEWER,
    )
    session.add(builtin)
    session.commit()
    session.expire_all()
    rows = list_runtime_skills_for_user(db_session=session, user=user)
    assert {skill.id, builtin.id} <= {row.id for row in rows}
    session.expunge_all()
    custom = next(row for row in rows if row.id == response.id)
    assert "First instructions" in read_custom_skill_bundle_instructions(custom)


@pytest.mark.parametrize("missing", ["blob", "bundle-link"])
def test_missing_current_bundle_never_uses_legacy(
    session: Session, user: User, missing: str
) -> None:
    response = api.create_custom_skill(
        upload(bundle("missing-reader")),
        True,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    version = skill.current_version
    if missing == "blob":
        version.bundle_file_id = "missing-current-blob"
    else:
        version.bundle_file_id = None
    session.commit()
    with pytest.raises(OnyxError, match="no longer kept"):
        read_custom_skill_bundle_instructions(skill)
    assert (
        validate_stored_custom_skill(skill, get_default_file_store()).is_valid is False
    )
    assert _assemble_fileset([skill], user, session) == {}


def test_lazy_validity_updates_version_and_ignores_replaced_version(
    session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("lazy-reader")),
        True,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    old = skill.current_version
    old.is_valid = None
    session.commit()
    observed = SkillValidityUpdate(skill.id, old.id, old.bundle_file_id, True)
    persist_skill_validity([observed])
    session.refresh(old)
    assert old.is_valid is True
    # Replacement publishes a different version; the late validation result is stale.
    api.replace_current_user_skill_bundle(
        skill.id,
        upload(bundle(skill.name, "New body")),
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    assert skill.current_version is not None and skill.current_version.id != old.id
    current = skill.current_version
    current.is_valid = None
    session.commit()
    persist_skill_validity([observed])
    session.refresh(current)
    assert current.is_valid is None
    assert "New body" in read_custom_skill_bundle_instructions(skill)


def test_completed_repair_does_not_authorize_cutover(
    tenant: str, session: Session, user: User
) -> None:
    response = api.create_custom_skill(
        upload(bundle("cutover-reader")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None
    get_kv_store().store(PROGRESS_KEY, "completed")
    assert check_cutover(tenant) == 0
    skill.current_version_id = None
    session.commit()
    assert check_cutover(tenant) == 1
    repair_skill_versions.run(tenant_id=tenant)
    assert check_cutover(tenant) == 0
    session.expire_all()
    assert not skill_version_repair_batch(session, None, drift_only=True)
    assert "First instructions" in read_custom_skill_bundle_instructions(skill)
    # A later old-writer edit blocks the gate even after another completed scan.
    skill.is_valid = False
    session.commit()
    assert check_cutover(tenant) == 1
    repair_skill_versions.run(tenant_id=tenant)
    assert check_cutover(tenant) == 0
