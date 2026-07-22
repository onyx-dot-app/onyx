from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    associate_built_in_skill__no_commit,
    create_external_app,
    upsert_external_app_user_credential,
)
from onyx.db.models import ExternalApp, ExternalApp__Skill, Skill, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.sandbox_proxy.request_evaluator import resolve_app_for_url
from onyx.server.features.build.external_apps.api import (
    create_built_in_external_app,
    create_custom_external_app,
    update_external_app_admin,
)
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
    CreateCustomExternalAppRequest,
    ExternalAppAdminResponse,
    UpdateExternalAppRequest,
)
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.utils.encryption import is_masked_credential

_AUTH_TEMPLATE = {"Authorization": "Bearer {api_key}"}
_UPSTREAM = ["https://api.example.com/*"]


def _create(
    db_session: Session,
    test_user: User,
    *,
    name: str = "My Custom App",
    auth_template: dict[str, str] | None = None,
    organization_credentials: dict[str, str] | None = None,
) -> ExternalAppAdminResponse:
    return create_custom_external_app(
        request=CreateCustomExternalAppRequest(
            name=name,
            upstream_url_patterns=_UPSTREAM,
            auth_template=_AUTH_TEMPLATE if auth_template is None else auth_template,
            organization_credentials=(
                {"api_key": "sk-test"}
                if organization_credentials is None
                else organization_credentials
            ),
        ),
        _=test_user,
        db_session=db_session,
    )


def _delete_app(db_session: Session, app_id: int) -> None:
    db_session.execute(delete(ExternalApp).where(ExternalApp.id == app_id))
    db_session.commit()


def _skill_ids(db_session: Session) -> set[UUID]:
    return set(db_session.scalars(select(Skill.id)))


def test_create_persists_gateway_without_creating_skill_content(
    db_session: Session,
    test_user: User,
) -> None:
    skills_before = _skill_ids(db_session)

    response = _create(db_session, test_user)

    assert response.app_type == ExternalAppType.CUSTOM
    assert response.name == "My Custom App"
    assert response.upstream_url_patterns == _UPSTREAM
    assert response.associated_skills == []
    assert _skill_ids(db_session) == skills_before
    assert (
        db_session.scalar(
            select(ExternalApp__Skill).where(
                ExternalApp__Skill.external_app_id == response.id
            )
        )
        is None
    )

    app = db_session.get(ExternalApp, response.id)
    assert app is not None
    assert app.auth_template == _AUTH_TEMPLATE
    assert app.organization_credentials.get_value(apply_mask=False) == {
        "api_key": "sk-test"
    }
    _delete_app(db_session, response.id)


def test_zero_skill_app_can_match_and_inject_user_credentials(
    db_session: Session,
    test_user: User,
) -> None:
    response = _create(
        db_session,
        test_user,
        organization_credentials={},
    )
    app = db_session.get(ExternalApp, response.id)
    assert app is not None
    assert app.associated_skills == []

    matched = resolve_app_for_url(
        "https://api.example.com/v10/users/@me",
        [app],
    )
    assert matched is app
    assert resolve_injection_headers(db_session, app.id, test_user.id) == {}

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=test_user.id,
        user_credentials={"api_key": "user-secret"},
    )
    assert resolve_injection_headers(db_session, app.id, test_user.id) == {
        "Authorization": "Bearer user-secret"
    }
    _delete_app(db_session, response.id)


def test_built_in_provisioning_reuses_an_orphaned_system_skill(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built_in_skill_id = f"test-provider-{uuid4().hex[:8]}"
    monkeypatch.setitem(
        EXTERNAL_APP_BUILT_IN_SKILL_IDS,
        ExternalAppType.CUSTOM,
        built_in_skill_id,
    )

    first_app = create_external_app(
        db_session=db_session,
        name="First provider",
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=_UPSTREAM,
        auth_template={},
        organization_credentials={},
    )
    first_skill = associate_built_in_skill__no_commit(db_session, first_app)
    db_session.commit()

    first_skill_id = first_skill.id
    db_session.delete(first_app)
    db_session.commit()
    assert db_session.get(Skill, first_skill_id) is not None

    second_app = create_external_app(
        db_session=db_session,
        name="Recreated provider",
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=_UPSTREAM,
        auth_template={},
        organization_credentials={},
    )
    second_skill = associate_built_in_skill__no_commit(db_session, second_app)
    db_session.commit()

    assert second_skill.id == first_skill_id
    assert second_app.associated_skills == [second_skill]
    assert (
        len(
            list(
                db_session.scalars(
                    select(Skill).where(Skill.built_in_skill_id == built_in_skill_id)
                )
            )
        )
        == 1
    )

    _delete_app(db_session, second_app.id)
    db_session.execute(delete(Skill).where(Skill.id == first_skill_id))
    db_session.commit()


def test_create_rejects_wildcard_host_without_persisting_resources(
    db_session: Session,
    test_user: User,
) -> None:
    app_ids_before = set(db_session.scalars(select(ExternalApp.id)))
    skill_ids_before = _skill_ids(db_session)

    with pytest.raises(OnyxError) as exc:
        create_custom_external_app(
            request=CreateCustomExternalAppRequest(
                name="Wildcard Host",
                upstream_url_patterns=["https://*.example.com/*"],
                auth_template=_AUTH_TEMPLATE,
                organization_credentials={},
            ),
            _=test_user,
            db_session=db_session,
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert set(db_session.scalars(select(ExternalApp.id))) == app_ids_before
    assert _skill_ids(db_session) == skill_ids_before


def test_create_allows_allowlist_only_app(
    db_session: Session,
    test_user: User,
) -> None:
    response = _create(
        db_session,
        test_user,
        auth_template={},
        organization_credentials={},
    )

    assert response.auth_template == {}
    assert response.organization_credentials == {}
    assert response.associated_skills == []
    _delete_app(db_session, response.id)


def test_edit_changes_only_gateway_configuration(
    db_session: Session,
    test_user: User,
) -> None:
    created = _create(db_session, test_user)
    skills_before = _skill_ids(db_session)

    edited = update_external_app_admin(
        external_app_id=created.id,
        request=UpdateExternalAppRequest(
            name="Renamed App",
            upstream_url_patterns=["https://api.example.com/v2/*"],
            auth_template={"X-API-Key": "{token}"},
            organization_credentials={"token": "updated-secret"},
        ),
        _=test_user,
        db_session=db_session,
    )

    assert edited.name == "Renamed App"
    assert edited.upstream_url_patterns == ["https://api.example.com/v2/*"]
    assert edited.associated_skills == []
    assert _skill_ids(db_session) == skills_before
    app = db_session.get(ExternalApp, created.id)
    assert app is not None
    assert app.organization_credentials.get_value(apply_mask=False) == {
        "token": "updated-secret"
    }
    _delete_app(db_session, created.id)


def test_admin_response_masks_secret_and_edit_preserves_it(
    db_session: Session,
    test_user: User,
) -> None:
    raw_secret = "super-secret-client-value-1234567890"
    created = _create(
        db_session,
        test_user,
        organization_credentials={"api_key": raw_secret},
    )
    returned = created.organization_credentials["api_key"]
    assert returned != raw_secret
    assert is_masked_credential(returned)

    edited = update_external_app_admin(
        external_app_id=created.id,
        request=UpdateExternalAppRequest(
            organization_credentials={"api_key": returned},
        ),
        _=test_user,
        db_session=db_session,
    )
    assert is_masked_credential(edited.organization_credentials["api_key"])

    db_session.expire_all()
    app = db_session.get(ExternalApp, created.id)
    assert app is not None
    assert app.organization_credentials.get_value(apply_mask=False) == {
        "api_key": raw_secret
    }
    _delete_app(db_session, created.id)


@pytest.mark.parametrize(
    ("create_request", "expected_detail"),
    [
        (
            CreateCustomExternalAppRequest(
                name=" ",
                upstream_url_patterns=_UPSTREAM,
                auth_template={},
                organization_credentials={},
            ),
            "name is required",
        ),
        (
            CreateCustomExternalAppRequest(
                name="No URLs",
                upstream_url_patterns=[],
                auth_template={},
                organization_credentials={},
            ),
            "At least one upstream URL pattern",
        ),
        (
            CreateCustomExternalAppRequest(
                name="Bad Header",
                upstream_url_patterns=_UPSTREAM,
                auth_template={"Authorization": ""},
                organization_credentials={},
            ),
            "must be a non-empty string",
        ),
    ],
)
def test_create_rejects_invalid_gateway_configuration(
    db_session: Session,
    test_user: User,
    create_request: CreateCustomExternalAppRequest,
    expected_detail: str,
) -> None:
    app_ids_before = set(db_session.scalars(select(ExternalApp.id)))

    with pytest.raises(OnyxError) as exc:
        create_custom_external_app(
            request=create_request,
            _=test_user,
            db_session=db_session,
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert expected_detail in exc.value.detail
    assert set(db_session.scalars(select(ExternalApp.id))) == app_ids_before


def test_built_in_endpoint_rejects_custom_app_type(
    db_session: Session,
    test_user: User,
) -> None:
    with pytest.raises(OnyxError) as exc:
        create_built_in_external_app(
            request=CreateBuiltInExternalAppRequest(
                name="Nope",
                app_type=ExternalAppType.CUSTOM,
                upstream_url_patterns=_UPSTREAM,
                auth_template=_AUTH_TEMPLATE,
                organization_credentials={},
            ),
            _=test_user,
            db_session=db_session,
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
