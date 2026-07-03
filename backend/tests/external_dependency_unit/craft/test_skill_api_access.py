"""Route-level skill access checks."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.db.enums import SkillAccessLevel
from onyx.db.enums import SkillSharePermission
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import create_custom_skill
from onyx.server.features.skill.api import fetch_skill_for_current_user
from onyx.server.features.skill.api import patch_current_user_skill
from onyx.server.features.skill.api import replace_current_user_skill_bundle
from onyx.server.features.skill.models import SkillPatchRequest
from tests.external_dependency_unit.craft.db_helpers import add_user_to_group
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_group
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_user


def _upload(filename: str) -> UploadFile:
    return cast(
        UploadFile,
        SimpleNamespace(file=io.BytesIO(b"bundle"), filename=filename),
    )


def test_curator_without_group_scope_cannot_patch_shared_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    curator = make_user(db_session, role=UserRole.CURATOR)
    group = make_group(db_session)
    add_user_to_group(db_session, curator, group)
    private_skill = make_skill(db_session, is_public=False, enabled=True)
    share_skill_with_group(db_session, private_skill, group)

    with pytest.raises(OnyxError) as exc_info:
        patch_current_user_skill(
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
        private_skill.id,
        user=user,
        db_session=db_session,
    )

    assert response.source == "custom"
    assert response.is_personal is False
    assert response.user_permission == SkillAccessLevel.VIEWER


def test_viewer_share_cannot_patch_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    shared_user = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(
        db_session,
        is_public=False,
        enabled=True,
        author_user_id=owner.id,
    )
    share_skill_with_user(
        db_session,
        private_skill,
        shared_user,
        SkillSharePermission.VIEWER,
    )

    with pytest.raises(OnyxError) as exc_info:
        patch_current_user_skill(
            private_skill.id,
            SkillPatchRequest(enabled=False),
            user=shared_user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    db_session.refresh(private_skill)
    assert private_skill.enabled is True


def test_create_reserved_slug_rejects_before_reading_bundle(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)
    read_bundle_file = MagicMock()
    monkeypatch.setattr(
        "onyx.server.features.skill.api.read_bundle_file",
        read_bundle_file,
    )

    with pytest.raises(OnyxError) as exc_info:
        create_custom_skill(
            bundle=_upload("pptx.zip"),
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    read_bundle_file.assert_not_called()


def test_replace_bundle_authorizes_before_reading_bundle(
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
    share_skill_with_user(
        db_session,
        private_skill,
        shared_user,
        SkillSharePermission.VIEWER,
    )
    read_bundle_file = MagicMock()
    monkeypatch.setattr(
        "onyx.server.features.skill.api.read_bundle_file",
        read_bundle_file,
    )

    with pytest.raises(OnyxError) as exc_info:
        replace_current_user_skill_bundle(
            private_skill.id,
            bundle=_upload("replace-test.zip"),
            user=shared_user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    read_bundle_file.assert_not_called()
