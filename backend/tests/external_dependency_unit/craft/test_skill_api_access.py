"""Route-level skill access checks."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.db.enums import (
    SkillAccessLevel,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import User, UserSkillPreference
from onyx.db.skill import set_skill_enabled_for_user, skill_user_states
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.api import (
    create_custom_skill,
    create_custom_skill_from_editor,
    delete_current_user_skill,
    fetch_custom_skill_sharing,
    fetch_skill_for_current_user,
    patch_current_user_skill,
    remove_current_user_skill_file,
    replace_current_user_skill_bundle,
    set_skill_enabled_for_current_user,
    share_current_user_skill,
    upload_current_user_skill_files,
)
from onyx.server.features.skill.models import (
    SkillEnableRequest,
    SkillPatchRequest,
    SkillShareRequest,
)
from onyx.skills.bundle import SKILL_MD_NAME, build_single_file_bundle, build_skill_md
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_external_app,
    make_group,
    make_skill,
    make_user,
    make_user_credential,
    share_skill_with_group,
    share_skill_with_user,
)


def _upload(filename: str, content: bytes = b"bundle") -> UploadFile:
    return cast(
        UploadFile,
        SimpleNamespace(file=io.BytesIO(content), filename=filename),
    )


def test_curator_without_group_scope_cannot_patch_shared_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    curator = make_user(db_session, is_group_manager=True)
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
    user = make_user(db_session, standard_account=True)
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


def test_fetch_associated_skill_reports_current_user_dependency_readiness(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    app = make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {token}"},
    )
    app.name = "Acme CRM"
    db_session.flush()

    disconnected = fetch_skill_for_current_user(
        skill.id,
        user=user,
        db_session=db_session,
    )

    assert disconnected.external_app is not None
    assert disconnected.external_app.external_app_id == app.id
    assert disconnected.external_app.name == "Acme CRM"
    assert disconnected.external_app.enabled is True
    assert disconnected.external_app.ready is False
    assert disconnected.enabled is False
    assert disconnected.can_toggle is False

    make_user_credential(
        db_session,
        app=app,
        user=user,
        user_credentials={"token": "connected"},
    )
    connected = fetch_skill_for_current_user(
        skill.id,
        user=user,
        db_session=db_session,
    )

    assert connected.external_app is not None
    assert connected.external_app.ready is True
    assert connected.enabled is False
    assert connected.can_toggle is True

    selected = set_skill_enabled_for_current_user(
        skill.id,
        SkillEnableRequest(enabled=True),
        user=user,
        db_session=db_session,
    )
    assert selected.enabled is True
    assert selected.external_app is not None
    assert selected.external_app.ready is True

    app.enabled = False
    db_session.flush()
    unavailable = fetch_skill_for_current_user(
        skill.id,
        user=user,
        db_session=db_session,
    )
    assert unavailable.enabled is True
    assert unavailable.can_toggle is True
    assert unavailable.external_app is not None
    assert unavailable.external_app.ready is False


def test_viewer_share_cannot_patch_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    shared_user = make_user(db_session, standard_account=True)
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
    user = make_user(db_session, standard_account=True)
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


def test_create_reserved_name_rejects_from_bundle_metadata(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, standard_account=True)
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
    user = make_user(db_session, standard_account=True)

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
    owner = make_user(db_session, standard_account=True)
    shared_user = make_user(db_session, standard_account=True)
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
    owner = make_user(db_session, standard_account=True)
    shared_user = make_user(db_session, standard_account=True)
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
    owner = make_user(db_session, standard_account=True)
    shared_user = make_user(db_session, standard_account=True)
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
    owner = make_user(db_session, standard_account=True)
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


@pytest.mark.parametrize("policy", list(SkillInstallationPolicy))
def test_admin_can_set_installation_policy(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    policy: SkillInstallationPolicy,
) -> None:
    admin = make_user(db_session, is_admin=True)
    skill = make_skill(db_session, is_public=True)
    skill.installation_policy = SkillInstallationPolicy.REQUIRED
    db_session.flush()
    push = MagicMock()
    monkeypatch.setattr("onyx.server.features.skill.api.push_skills_for_users", push)
    response = share_current_user_skill(
        skill.id,
        SkillShareRequest(installation_policy=policy),
        user=admin,
        db_session=db_session,
    )
    assert response.installation_policy == policy
    assert response.enabled == (policy != SkillInstallationPolicy.AVAILABLE)
    assert response.can_toggle == (policy != SkillInstallationPolicy.REQUIRED)
    push.assert_called_once()


def test_skill_owner_cannot_change_installation_policy(db_session: Session) -> None:
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True, author_user_id=owner.id)
    with pytest.raises(OnyxError) as error:
        share_current_user_skill(
            skill.id,
            SkillShareRequest(installation_policy=SkillInstallationPolicy.REQUIRED),
            user=owner,
            db_session=db_session,
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_required_skill_owner_cannot_delete_but_can_change_audience(
    db_session: Session,
) -> None:
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True, author_user_id=owner.id)
    skill.installation_policy = SkillInstallationPolicy.REQUIRED
    db_session.flush()
    with pytest.raises(OnyxError):
        delete_current_user_skill(skill.id, user=owner, db_session=db_session)
    response = patch_current_user_skill(
        skill.id,
        SkillPatchRequest(public_permission=None),
        user=owner,
        db_session=db_session,
    )
    assert response.public_permission is None
    assert response.installation_policy == SkillInstallationPolicy.REQUIRED


@pytest.mark.parametrize("is_admin", [False, True])
def test_editor_creation_saves_sharing_with_skill(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    is_admin: bool,
) -> None:
    owner = make_user(db_session, is_admin=is_admin, standard_account=not is_admin)
    invited = make_user(db_session, standard_account=True)
    push = MagicMock()
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skill_to_affected_sandboxes", push
    )
    sharing = {
        "public_permission": None,
        "user_shares": [{"user_id": str(invited.id), "permission": "VIEWER"}],
    }
    if is_admin:
        sharing["installation_policy"] = "REQUIRED"
    response = create_custom_skill_from_editor(
        name="shared-at-creation",
        description="A shared skill",
        instructions_markdown="Write a report.",
        sharing=json.dumps(sharing),
        user=owner,
        db_session=db_session,
    )
    assert response.public_permission is None
    assert [share.user.id for share in response.user_shares] == [invited.id]
    visible = fetch_skill_for_current_user(
        response.id, user=invited, db_session=db_session
    )
    assert visible.enabled is is_admin
    assert visible.can_toggle is not is_admin
    push.assert_called_once()


def test_editor_creation_rejects_non_admin_installation_policy(
    db_session: Session,
) -> None:
    owner = make_user(db_session, standard_account=True)
    with pytest.raises(OnyxError) as error:
        create_custom_skill_from_editor(
            name="unauthorized-required-skill",
            description="A skill",
            instructions_markdown="Write a report.",
            sharing='{"installation_policy":"REQUIRED"}',
            user=owner,
            db_session=db_session,
        )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.parametrize("editor", [False, True])
def test_sharing_metadata_requires_edit_access_without_reading_bundle(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, editor: bool
) -> None:
    owner = make_user(db_session, standard_account=True)
    invited = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=False, author_user_id=owner.id)
    share_skill_with_user(
        db_session,
        skill,
        invited,
        permission=SkillSharePermission.EDITOR
        if editor
        else SkillSharePermission.VIEWER,
    )
    read_bundle = MagicMock(
        side_effect=AssertionError("Sharing must not read the bundle")
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.read_custom_skill_bundle_bytes", read_bundle
    )
    if editor:
        response = fetch_custom_skill_sharing(
            skill.id, user=invited, db_session=db_session
        )
        assert response.owner is not None and response.owner.id == owner.id
        assert [share.user.id for share in response.user_shares] == [invited.id]
    else:
        with pytest.raises(OnyxError) as error:
            fetch_custom_skill_sharing(skill.id, user=invited, db_session=db_session)
        assert error.value.error_code == OnyxErrorCode.NOT_FOUND
    read_bundle.assert_not_called()


def test_required_creation_preserves_same_name_personal_preference(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_user(db_session, is_admin=True)
    personal = make_skill(
        db_session, name="required-creation-conflict", author_user_id=owner.id
    )
    set_skill_enabled_for_user(
        skill_id=personal.id, enabled=True, user=owner, db_session=db_session
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skill_to_affected_sandboxes", MagicMock()
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users", MagicMock()
    )
    response = create_custom_skill_from_editor(
        name=personal.name,
        description="Admin required skill",
        instructions_markdown="Follow the organization instructions.",
        sharing='{"installation_policy":"REQUIRED"}',
        user=owner,
        db_session=db_session,
    )
    assert response.enabled
    assert db_session.get(UserSkillPreference, (owner.id, response.id)) is None
    personal_preference = db_session.get(UserSkillPreference, (owner.id, personal.id))
    assert personal_preference is not None and personal_preference.enabled
    share_current_user_skill(
        response.id,
        SkillShareRequest(installation_policy=SkillInstallationPolicy.DEFAULT),
        user=owner,
        db_session=db_session,
    )
    states = skill_user_states(owner, [personal.id, response.id], db_session)
    assert states[personal.id].enabled
    assert not states[response.id].enabled


@pytest.mark.parametrize("is_admin", [False, True])
@pytest.mark.parametrize("sharing", [{}, {"user_shares": []}])
def test_sharing_without_policy_preserves_existing_policy(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    is_admin: bool,
    sharing: dict[str, object],
) -> None:
    owner = make_user(db_session, is_admin=is_admin, standard_account=not is_admin)
    skill = make_skill(db_session, author_user_id=owner.id)
    skill.installation_policy = SkillInstallationPolicy.REQUIRED
    db_session.flush()
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users", MagicMock()
    )
    response = share_current_user_skill(
        skill.id,
        SkillShareRequest.model_validate(sharing),
        user=owner,
        db_session=db_session,
    )
    assert response.installation_policy == SkillInstallationPolicy.REQUIRED
    db_session.refresh(skill)
    assert skill.installation_policy == SkillInstallationPolicy.REQUIRED


def test_sharing_rejects_explicit_null_policy() -> None:
    with pytest.raises(ValidationError):
        SkillShareRequest.model_validate({"installation_policy": None})


def test_creation_response_includes_saved_group_shares(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = make_user(db_session, is_admin=True)
    group = make_group(db_session)
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skill_to_affected_sandboxes", MagicMock()
    )
    response = create_custom_skill_from_editor(
        name="shared-with-group-at-creation",
        description="A shared skill",
        instructions_markdown="Write a report.",
        sharing=json.dumps(
            {"group_shares": [{"group_id": group.id, "permission": "VIEWER"}]}
        ),
        user=admin,
        db_session=db_session,
    )
    assert [share.group_id for share in response.group_shares] == [group.id]
    assert not response.is_personal
