from __future__ import annotations

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.external_apps.credentials import resolve_injection_headers
from tests.external_dependency_unit.craft.db_helpers import make_external_app
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import make_user_credential

_BEARER = {"Authorization": "Bearer {access_token}"}


def test_user_credential_fills_header(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    app = make_external_app(
        db_session,
        skill=make_skill(db_session),
        auth_template=_BEARER,
        app_type=ExternalAppType.SLACK,
    )
    make_user_credential(
        db_session, app=app, user=user, user_credentials={"access_token": "xoxb-1"}
    )

    assert resolve_injection_headers(db_session, app.id, user.id) == {
        "Authorization": "Bearer xoxb-1"
    }


def test_org_credential_fills_without_user_cred(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    app = make_external_app(
        db_session,
        skill=make_skill(db_session),
        auth_template={"X-Api-Key": "{api_key}"},
        organization_credentials={"api_key": "org-key"},
    )

    assert resolve_injection_headers(db_session, app.id, user.id) == {
        "X-Api-Key": "org-key"
    }


def test_user_credential_overrides_org(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    app = make_external_app(
        db_session,
        skill=make_skill(db_session),
        auth_template={"Authorization": "Bearer {token}"},
        organization_credentials={"token": "org"},
    )
    make_user_credential(
        db_session, app=app, user=user, user_credentials={"token": "user"}
    )

    assert resolve_injection_headers(db_session, app.id, user.id) == {
        "Authorization": "Bearer user"
    }


def test_disabled_app_injects_nothing(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """The linked skill's enabled flag is the proxy's kill switch."""
    user = make_user(db_session)
    app = make_external_app(
        db_session,
        skill=make_skill(db_session, enabled=False),
        auth_template=_BEARER,
    )
    make_user_credential(
        db_session, app=app, user=user, user_credentials={"access_token": "x"}
    )

    assert resolve_injection_headers(db_session, app.id, user.id) == {}


def test_missing_user_credential_omits_header(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    app = make_external_app(
        db_session, skill=make_skill(db_session), auth_template=_BEARER
    )

    # User hasn't connected -> placeholder unfilled -> header dropped.
    assert resolve_injection_headers(db_session, app.id, user.id) == {}


def test_unknown_app_returns_empty(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    assert resolve_injection_headers(db_session, 999_999, user.id) == {}
