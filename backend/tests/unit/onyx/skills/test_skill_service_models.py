import io
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.configs.app_configs import MAX_PERSONAL_SKILLS_PER_USER
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import create_personal_skill
from onyx.server.features.skill.api import patch_personal_skill
from onyx.server.features.skill.api import replace_personal_skill_bundle
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import PersonalSkillPatchRequest
from onyx.server.features.skill.service import ensure_owned_personal_skill


def _custom_skill(
    *,
    author_user_id: UUID | None = None,
    public_permission: SkillSharePermission | None = None,
) -> Skill:
    return Skill(
        id=uuid4(),
        slug=f"skill-{uuid4().hex[:8]}",
        name="Skill",
        description="Description",
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
        built_in_skill_id=None,
        author_user_id=author_user_id,
        public_permission=public_permission,
        enabled=True,
    )


def _upload(filename: str) -> UploadFile:
    return cast(
        UploadFile,
        SimpleNamespace(file=io.BytesIO(b"bundle"), filename=filename),
    )


def test_custom_skill_response_public_state_comes_from_public_permission() -> None:
    private_skill = _custom_skill(public_permission=None)
    org_skill = _custom_skill(public_permission=SkillSharePermission.VIEWER)

    assert (
        CustomSkillResponse.from_model(private_skill, group_ids=[]).is_public is False
    )
    assert CustomSkillResponse.from_model(org_skill, group_ids=[]).is_public is True


def test_custom_skill_response_uses_direct_grants_for_personal_state() -> None:
    skill = _custom_skill(public_permission=None)

    response = CustomSkillResponse.from_model(
        skill,
        group_ids=[],
        has_grants=True,
    )

    assert response.is_personal is False


def test_directly_shared_skill_cannot_use_personal_mutation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    author_user_id = uuid4()
    skill = _custom_skill(author_user_id=author_user_id)
    user = cast(User, SimpleNamespace(id=author_user_id))
    db_session = cast(Session, MagicMock())
    monkeypatch.setattr(
        "onyx.server.features.skill.service.skill_ids_with_grants",
        lambda _skill_ids, _db_session: {skill.id},
    )

    with pytest.raises(OnyxError):
        ensure_owned_personal_skill(skill, user, db_session)


def test_create_personal_skill_rejects_quota_before_reading_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = cast(User, SimpleNamespace(id=uuid4()))
    db_session = cast(Session, MagicMock())
    read_bundle_file = MagicMock()

    monkeypatch.setattr(
        "onyx.server.features.skill.api.lock_personal_skills_for_user",
        lambda _user_id, _db_session: None,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.count_personal_skills_for_user",
        lambda _user_id, _db_session: MAX_PERSONAL_SKILLS_PER_USER,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.service.read_bundle_file", read_bundle_file
    )

    with pytest.raises(OnyxError):
        create_personal_skill(
            bundle=_upload("quota-test.zip"),
            user=user,
            db_session=db_session,
        )

    read_bundle_file.assert_not_called()


def test_replace_personal_skill_bundle_authorizes_before_reading_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = _custom_skill(author_user_id=uuid4())
    user = cast(User, SimpleNamespace(id=uuid4()))
    db_session = cast(Session, MagicMock())
    read_bundle_file = MagicMock()

    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_skill_by_id",
        lambda _skill_id, _db_session: skill,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.service.read_bundle_file", read_bundle_file
    )

    with pytest.raises(OnyxError):
        replace_personal_skill_bundle(
            skill_id=skill.id,
            bundle=_upload("replace-test.zip"),
            user=user,
            db_session=db_session,
        )

    read_bundle_file.assert_not_called()


def test_noop_personal_patch_does_not_push_sandboxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    skill = _custom_skill(author_user_id=user_id)
    user = cast(User, SimpleNamespace(id=user_id))
    db_session = cast(Session, MagicMock())
    push_skills_for_users = MagicMock()

    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_skill_by_id",
        lambda _skill_id, _db_session: skill,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.service.skill_ids_with_grants",
        lambda _skill_ids, _db_session: set(),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.affected_user_ids_for_skill",
        lambda _skill, _db_session: {user_id},
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.patch_skill",
        lambda **_kwargs: skill,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users",
        push_skills_for_users,
    )

    response = patch_personal_skill(
        skill_id=skill.id,
        patch_req=PersonalSkillPatchRequest(enabled=True),
        user=user,
        db_session=db_session,
    )

    assert response.id == skill.id
    push_skills_for_users.assert_not_called()
