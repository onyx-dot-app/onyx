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
from onyx.db.models import UserSkillPreference
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import create_custom_skill
from onyx.server.features.skill.api import create_custom_skill_from_editor
from onyx.server.features.skill.api import fetch_skill_for_current_user
from onyx.server.features.skill.api import patch_current_user_skill
from onyx.server.features.skill.api import remove_current_user_skill_file
from onyx.server.features.skill.api import replace_current_user_skill_bundle
from onyx.server.features.skill.api import set_skill_enabled_for_current_user
from onyx.server.features.skill.api import upload_current_user_skill_files
from onyx.server.features.skill.models import SkillEnableRequest
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.skills.bundle import build_single_file_bundle
from onyx.skills.bundle import build_skill_md
from onyx.skills.bundle import SKILL_MD_NAME
from tests.external_dependency_unit.craft.db_helpers import add_user_to_group
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_group
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_user


def _upload(filename: str, content: bytes = b"bundle") -> UploadFile:
    return cast(
        UploadFile,
        SimpleNamespace(file=io.BytesIO(content), filename=filename),
    )


def test_curator_without_group_scope_cannot_patch_shared_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    curator = make_user(db_session, role=UserRole.CURATOR)
    group = make_group(db_session)
    add_user_to_group(db_session, curator, group)
    private_skill = make_skill(db_session, is_public=False)
    share_skill_with_group(db_session, private_skill, group)

    with pytest.raises(OnyxError) as exc_info:
        patch_current_user_skill(
            private_skill.id,
            SkillPatchRequest(description="unauthorized edit"),
            user=curator,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND


def test_fetch_direct_shared_skill_is_not_personal(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(db_session, is_public=False)
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
            SkillPatchRequest(description="unauthorized edit"),
            user=shared_user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND


def test_preference_commit_succeeds_when_sandbox_push_fails(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)
    skill = make_skill(db_session, is_public=True)

    def fail_sandbox_lookup(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("sandbox unavailable")

    monkeypatch.setattr(
        "onyx.skills.push.get_sandbox_user_map",
        fail_sandbox_lookup,
    )

    response = set_skill_enabled_for_current_user(
        skill.id,
        SkillEnableRequest(enabled=True),
        user=user,
        db_session=db_session,
    )

    preference = db_session.get(
        UserSkillPreference,
        {"user_id": user.id, "skill_id": skill.id},
    )
    assert response.enabled is True
    assert preference is not None
    assert preference.enabled is True


def test_create_reserved_name_rejects_from_bundle_metadata(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)
    bundle = build_single_file_bundle(
        SKILL_MD_NAME,
        build_skill_md(
            name="pptx",
            description="Reserved built-in name",
            instructions_markdown="Do the thing.",
        ).encode("utf-8"),
    )

    with pytest.raises(OnyxError) as exc_info:
        create_custom_skill(
            bundle=_upload("unrelated-filename.zip", bundle),
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == "skill name 'pptx' is reserved"


def test_editor_create_rejects_whitespace_only_fields(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)

    with pytest.raises(OnyxError) as exc_info:
        create_custom_skill_from_editor(
            name=" ",
            description="\t",
            instructions_markdown="\n",
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == (
        "Skill name, description, and instructions cannot be empty."
    )


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


def test_upload_files_authorizes_before_reading_upload(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    shared_user = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(
        db_session,
        is_public=False,
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
        upload_current_user_skill_files(
            private_skill.id,
            upload=_upload("notes.md"),
            user=shared_user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    read_bundle_file.assert_not_called()


def test_remove_file_authorizes_before_reading_bundle(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    shared_user = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(
        db_session,
        is_public=False,
        author_user_id=owner.id,
    )
    share_skill_with_user(
        db_session,
        private_skill,
        shared_user,
        SkillSharePermission.VIEWER,
    )
    read_bundle = MagicMock()
    monkeypatch.setattr(
        "onyx.server.features.skill.api.read_custom_skill_bundle_bytes",
        read_bundle,
    )

    with pytest.raises(OnyxError) as exc_info:
        remove_current_user_skill_file(
            private_skill.id,
            path="references/context.md",
            user=shared_user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    read_bundle.assert_not_called()


def test_remove_file_rejects_empty_path_before_reading_bundle(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    private_skill = make_skill(
        db_session,
        is_public=False,
        author_user_id=owner.id,
    )
    read_bundle = MagicMock()
    monkeypatch.setattr(
        "onyx.server.features.skill.api.read_custom_skill_bundle_bytes",
        read_bundle,
    )

    with pytest.raises(OnyxError) as exc_info:
        remove_current_user_skill_file(
            private_skill.id,
            path="",
            user=owner,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == "Skill file path cannot be empty"
    read_bundle.assert_not_called()
