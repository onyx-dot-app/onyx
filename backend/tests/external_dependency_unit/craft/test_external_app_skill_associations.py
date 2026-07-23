from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, SkillSharePermission
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    create_external_app,
    get_external_app_by_skill_id,
    get_skills_for_external_app,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import ExternalApp, Skill, User, UserRole, UserSkillPreference
from onyx.db.skill import set_skill_public_permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.external_apps.api import (
    update_external_app_admin,
)
from onyx.server.features.build.external_apps.models import UpdateExternalAppRequest
from onyx.server.features.skill.api import create_custom_skill_from_editor
from onyx.skills.ingest import delete_bundle_blob
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_external_app,
    make_sandbox,
    make_skill,
    make_user,
)


def _make_app(db_session: Session, name: str = "Acme CRM") -> int:
    return create_external_app(
        db_session=db_session,
        name=name,
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    ).id


def test_associate_promotes_visibility_and_preserves_preferences(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    skill = make_skill(
        db_session,
        is_public=False,
        author_user_id=owner.id,
    )
    db_session.add(
        UserSkillPreference(user_id=owner.id, skill_id=skill.id, name=skill.name)
    )
    db_session.flush()
    app_id = _make_app(db_session)
    app = db_session.get(ExternalApp, app_id)
    assert app is not None
    app.enabled = False
    db_session.flush()

    associated = associate_custom_skill_with_external_app__no_commit(
        db_session,
        external_app_id=app_id,
        skill_id=skill.id,
    )

    assert associated.public_permission == SkillSharePermission.VIEWER
    dependency = get_external_app_by_skill_id(db_session, skill.id)
    assert dependency is not None
    assert dependency.id == app_id
    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": owner.id, "skill_id": skill.id},
        )
        is not None
    )


def test_associate_rejects_built_in_and_already_associated_skills(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    first_app_id = _make_app(db_session, "First app")
    second_app_id = _make_app(db_session, "Second app")
    built_in = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"association-test-{uuid4().hex[:8]}",
    )
    custom = make_skill(db_session, is_public=True)
    associate_custom_skill_with_external_app__no_commit(
        db_session,
        external_app_id=first_app_id,
        skill_id=custom.id,
    )

    with pytest.raises(OnyxError) as built_in_error:
        associate_custom_skill_with_external_app__no_commit(
            db_session,
            external_app_id=first_app_id,
            skill_id=built_in.id,
        )
    assert built_in_error.value.error_code == OnyxErrorCode.INVALID_INPUT

    with pytest.raises(OnyxError) as duplicate_error:
        associate_custom_skill_with_external_app__no_commit(
            db_session,
            external_app_id=second_app_id,
            skill_id=custom.id,
        )
    assert duplicate_error.value.error_code == OnyxErrorCode.DUPLICATE_RESOURCE
    dependency = get_external_app_by_skill_id(db_session, custom.id)
    assert dependency is not None
    assert dependency.id == first_app_id


def test_unlink_retains_skill_visibility_content_and_preferences(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    skill = make_skill(db_session, is_public=True, author_user_id=owner.id)
    original_bundle_file_id = skill.bundle_file_id
    db_session.add(
        UserSkillPreference(user_id=owner.id, skill_id=skill.id, name=skill.name)
    )
    app_id = _make_app(db_session)
    associate_custom_skill_with_external_app__no_commit(
        db_session,
        external_app_id=app_id,
        skill_id=skill.id,
    )

    affected = replace_custom_skill_associations__no_commit(
        db_session,
        external_app_id=app_id,
        skill_ids=[],
    )
    unlinked = affected[0]

    assert unlinked.public_permission == SkillSharePermission.VIEWER
    assert unlinked.bundle_file_id == original_bundle_file_id
    assert get_external_app_by_skill_id(db_session, skill.id) is None
    assert (
        db_session.get(
            UserSkillPreference,
            {"user_id": owner.id, "skill_id": skill.id},
        )
        is not None
    )
    set_skill_public_permission(
        skill=unlinked,
        public_permission=None,
        db_session=db_session,
    )
    assert unlinked.public_permission is None


def test_replacing_custom_associations_preserves_provider_skill(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    provider_skill = make_built_in_skill_row(
        db_session,
        built_in_skill_id=f"provider-association-{uuid4().hex[:8]}",
    )
    app = make_external_app(
        db_session,
        skill=provider_skill,
        auth_template={},
    )
    custom_skill = make_skill(db_session, is_public=False)

    replace_custom_skill_associations__no_commit(
        db_session,
        external_app_id=app.id,
        skill_ids=[custom_skill.id],
    )
    assert {skill.id for skill in get_skills_for_external_app(db_session, app.id)} == {
        provider_skill.id,
        custom_skill.id,
    }

    replace_custom_skill_associations__no_commit(
        db_session,
        external_app_id=app.id,
        skill_ids=[],
    )
    assert get_skills_for_external_app(db_session, app.id) == [provider_skill]


def test_app_update_batches_associations_into_one_sandbox_refresh(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    other_user = make_user(db_session, role=UserRole.BASIC)
    make_sandbox(db_session, owner)
    make_sandbox(db_session, other_user)
    skill = make_skill(
        db_session,
        is_public=False,
        author_user_id=owner.id,
    )
    skill.is_valid = False
    second_skill = make_skill(
        db_session,
        is_public=False,
        author_user_id=owner.id,
    )
    app_id = _make_app(db_session)
    pushed_user_sets: list[set[UUID]] = []
    monkeypatch.setattr(
        "onyx.server.features.build.external_apps.api.push_skills_for_users",
        lambda user_ids, _db: pushed_user_sets.append(user_ids),
    )

    linked = update_external_app_admin(
        external_app_id=app_id,
        request=UpdateExternalAppRequest(
            name="Renamed CRM",
            associated_skill_ids=[skill.id, second_skill.id],
        ),
        _=test_user,
        db_session=db_session,
    )

    assert {summary.id for summary in linked.associated_skills} == {
        skill.id,
        second_skill.id,
    }
    assert linked.name == "Renamed CRM"
    assert (
        next(
            summary for summary in linked.associated_skills if summary.id == skill.id
        ).is_valid
        is False
    )
    assert {owner.id, other_user.id} <= pushed_user_sets[0]
    assert len(pushed_user_sets) == 1

    unlinked = update_external_app_admin(
        external_app_id=app_id,
        request=UpdateExternalAppRequest(associated_skill_ids=[]),
        _=test_user,
        db_session=db_session,
    )

    assert unlinked.associated_skills == []
    assert len(pushed_user_sets) == 2


def test_editor_creation_with_app_context_is_atomic_and_not_auto_enabled(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN)
    app_id = _make_app(db_session)
    response = create_custom_skill_from_editor(
        name=f"associated-{uuid4().hex[:8]}",
        description="Looks up CRM records.",
        instructions_markdown="Use the CRM app to look up the requested record.",
        auto_enable=True,
        external_app_id=app_id,
        user=admin,
        db_session=db_session,
    )
    skill = db_session.scalar(select(Skill).where(Skill.id == response.id))
    assert skill is not None
    bundle_file_id = skill.bundle_file_id

    try:
        assert response.public_permission == SkillSharePermission.VIEWER
        assert response.external_app is not None
        assert response.external_app.external_app_id == app_id
        assert response.enabled is False
        assert (
            db_session.scalar(
                select(UserSkillPreference).where(
                    UserSkillPreference.user_id == admin.id,
                    UserSkillPreference.skill_id == skill.id,
                )
            )
            is None
        )
    finally:
        db_session.delete(skill)
        db_session.commit()
        if bundle_file_id is not None:
            delete_bundle_blob(get_default_file_store(), bundle_file_id)


def test_editor_app_context_requires_an_admin_before_writing_skill_content(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    user = make_user(db_session, role=UserRole.BASIC)
    app_id = _make_app(db_session)
    skill_ids_before = set(db_session.scalars(select(Skill.id)))

    with pytest.raises(OnyxError) as exc_info:
        create_custom_skill_from_editor(
            name=f"unauthorized-{uuid4().hex[:8]}",
            description="Should not be created.",
            instructions_markdown="Do not persist this bundle.",
            external_app_id=app_id,
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert set(db_session.scalars(select(Skill.id))) == skill_ids_before
