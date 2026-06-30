from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import CustomSkillResponse
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
