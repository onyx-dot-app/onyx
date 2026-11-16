"""The external app writers also write the plugin rows of their custom skills.

The skills here start with no plugin row, as if an older server made them, so
each writer also shows that the plugin is made from the legacy rows first."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, SkillInstallationPolicy, SkillSharePermission
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    create_external_app,
    delete_external_app,
    disconnect_external_app_for_user,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import Plugin, Skill__User, User, UserSkillPreference
from onyx.db.skill import set_skill_public_permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
from tests.utils.plugin_access import (
    ORGANIZATION_LIBRARY_ID,
    plugin_access_mismatches,
)


def _make_app(db_session: Session) -> int:
    return create_external_app(
        db_session=db_session,
        name="Acme CRM",
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    ).id


def _assert_published(db_session: Session, skill_id: object) -> None:
    plugin = db_session.get(Plugin, skill_id)
    assert plugin is not None
    db_session.refresh(plugin)
    assert plugin.marketplace_id == ORGANIZATION_LIBRARY_ID
    assert plugin.published_version_id == plugin.current_version_id


def test_associate_publishes_the_plugin(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    viewer = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id, with_plugin=False)
    db_session.add_all(
        [
            UserSkillPreference(user_id=owner.id, skill_id=skill.id, name=skill.name),
            Skill__User(
                skill_id=skill.id,
                user_id=viewer.id,
                permission=SkillSharePermission.EDITOR,
            ),
        ]
    )
    db_session.flush()

    associate_custom_skill_with_external_app__no_commit(
        db_session, external_app_id=_make_app(db_session), skill_id=skill.id
    )

    _assert_published(db_session, skill.id)
    assert plugin_access_mismatches(db_session, [skill.id]) == []


def test_associate_with_a_used_name_returns_conflict(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    published = make_skill(
        db_session, author_user_id=make_user(db_session).id, with_plugin=False
    )
    set_skill_public_permission(
        skill=published,
        public_permission=SkillSharePermission.VIEWER,
        db_session=db_session,
    )
    clash = make_skill(db_session, name=published.name, with_plugin=False)
    app_id = _make_app(db_session)

    with pytest.raises(OnyxError) as exc:
        with db_session.begin_nested():
            associate_custom_skill_with_external_app__no_commit(
                db_session, external_app_id=app_id, skill_id=clash.id
            )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    with pytest.raises(OnyxError) as exc:
        with db_session.begin_nested():
            replace_custom_skill_associations__no_commit(
                db_session, external_app_id=app_id, skill_ids=[clash.id]
            )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    db_session.refresh(clash)
    assert clash.public_permission is None


def test_replace_associations_publishes_each_plugin(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    skills = [
        make_skill(db_session, author_user_id=owner.id, with_plugin=False)
        for _ in range(2)
    ]

    replace_custom_skill_associations__no_commit(
        db_session,
        external_app_id=_make_app(db_session),
        skill_ids=[skill.id for skill in skills],
    )

    for skill in skills:
        _assert_published(db_session, skill.id)
    assert plugin_access_mismatches(db_session, [skill.id for skill in skills]) == []


def test_delete_app_resets_install_setting_and_choices(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id, with_plugin=False)
    app_id = _make_app(db_session)
    associate_custom_skill_with_external_app__no_commit(
        db_session, external_app_id=app_id, skill_id=skill.id
    )
    skill.installation_policy = SkillInstallationPolicy.DEFAULT
    db_session.add(
        UserSkillPreference(user_id=owner.id, skill_id=skill.id, name=skill.name)
    )
    db_session.flush()
    # The plugin misses the setting and the choice, as after an old write.
    assert plugin_access_mismatches(db_session, [skill.id]) != []

    delete_external_app(db_session, app_id)

    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None
    db_session.refresh(plugin)
    assert plugin.installation_policy is None
    assert plugin_access_mismatches(db_session, [skill.id]) == []


def test_disconnect_removes_only_enabled_choices(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    owner = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    enabled = make_skill(db_session, author_user_id=owner.id, with_plugin=False)
    disabled = make_skill(db_session, author_user_id=owner.id, with_plugin=False)
    app_id = _make_app(db_session)
    replace_custom_skill_associations__no_commit(
        db_session, external_app_id=app_id, skill_ids=[enabled.id, disabled.id]
    )
    db_session.add_all(
        [
            UserSkillPreference(
                user_id=owner.id, skill_id=enabled.id, name=enabled.name, enabled=True
            ),
            UserSkillPreference(
                user_id=owner.id,
                skill_id=disabled.id,
                name=disabled.name,
                enabled=False,
            ),
            UserSkillPreference(
                user_id=other.id, skill_id=enabled.id, name=enabled.name, enabled=True
            ),
        ]
    )
    db_session.flush()
    # Drop the plugins: the disconnect makes them from the legacy rows first.
    db_session.delete(db_session.get(Plugin, enabled.id))
    db_session.delete(db_session.get(Plugin, disabled.id))
    db_session.flush()

    disconnect_external_app_for_user(
        db_session, external_app_id=app_id, user_id=owner.id
    )

    assert plugin_access_mismatches(db_session, [enabled.id, disabled.id]) == []
    assert db_session.get(
        UserSkillPreference, {"user_id": other.id, "skill_id": enabled.id}
    )
    assert (
        db_session.get(
            UserSkillPreference, {"user_id": owner.id, "skill_id": enabled.id}
        )
        is None
    )


def test_associate_refuses_invalid_skill_with_no_plugin(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    skill = make_skill(db_session, with_plugin=False)
    skill.is_valid = False
    db_session.flush()
    app_id = _make_app(db_session)

    with pytest.raises(OnyxError) as exc:
        with db_session.begin_nested():
            associate_custom_skill_with_external_app__no_commit(
                db_session, external_app_id=app_id, skill_id=skill.id
            )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    with pytest.raises(OnyxError) as exc:
        with db_session.begin_nested():
            replace_custom_skill_associations__no_commit(
                db_session, external_app_id=app_id, skill_ids=[skill.id]
            )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
