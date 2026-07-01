"""Route-level skill access checks."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import fetch_skill_for_current_user
from onyx.server.features.skill.api import patch_custom_skill
from onyx.server.features.skill.api import patch_personal_skill
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import PersonalSkillPatchRequest
from onyx.server.features.skill.models import SkillPatchRequest
from tests.external_dependency_unit.craft.db_helpers import add_user_to_group
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_group
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_user


def test_admin_mutation_uses_edit_policy_for_curator_scope(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curator = make_user(db_session, role=UserRole.CURATOR)
    group = make_group(db_session)
    add_user_to_group(db_session, curator, group)
    private_skill = make_skill(db_session, is_public=False, enabled=True)
    share_skill_with_group(db_session, private_skill, group)
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users",
        lambda *_args: None,
    )

    with pytest.raises(OnyxError) as exc_info:
        patch_custom_skill(
            private_skill.id,
            SkillPatchRequest(enabled=False),
            user=curator,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    db_session.refresh(private_skill)
    assert private_skill.enabled is True


def test_fetch_direct_shared_skill_is_not_personal(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(db_session, is_public=False, enabled=True)
    share_skill_with_user(db_session, private_skill, user)

    response = fetch_skill_for_current_user(
        str(private_skill.id),
        user=user,
        db_session=db_session,
    )

    assert isinstance(response, CustomSkillResponse)
    assert response.is_personal is False


def test_personal_mutation_rejects_direct_shared_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    shared_user = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(
        db_session,
        is_public=False,
        enabled=True,
        author_user_id=owner.id,
    )
    share_skill_with_user(db_session, private_skill, shared_user)
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users",
        lambda *_args: None,
    )

    with pytest.raises(OnyxError) as exc_info:
        patch_personal_skill(
            private_skill.id,
            PersonalSkillPatchRequest(enabled=False),
            user=owner,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.refresh(private_skill)
    assert private_skill.enabled is True
