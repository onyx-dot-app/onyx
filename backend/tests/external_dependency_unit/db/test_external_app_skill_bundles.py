"""End-to-end tests for built-in external app skill-bundle delivery.

Covers the loader (`get_builtin_external_app_bundle`), the DB helper
(`get_authenticated_builtin_apps_for_user`), and that the bundle lands
in a user's skill fileset under the reserved `_external_apps/` prefix
(so it is structurally excluded from the skills tab).

Setup writes flush but never commit; `rollback_session` discards them
at teardown so each test sees a clean catalog.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import create_external_app__no_commit
from onyx.db.external_app import get_authenticated_builtin_apps_for_user
from onyx.db.external_app import upsert_external_app_user_credential__no_commit
from onyx.db.models import ExternalApp
from onyx.external_apps.skill_bundle import get_builtin_external_app_bundle
from onyx.server.features.build.sandbox.models import FileSet
from onyx.skills.push import _EXTERNAL_APPS_DIR
from onyx.skills.push import _merge_external_app_bundles
from tests.external_dependency_unit.conftest import create_test_user

# Slack's provider auth_template references {access_token}; with empty
# org credentials the user must supply access_token to be "authenticated".
_SLACK_AUTH_TEMPLATE = {"Authorization": "Bearer {access_token}"}
_FULL_USER_CREDS = {"access_token": "USER_SLACK_TOKEN"}


@pytest.fixture
def rollback_session(db_session: Session) -> Generator[Session, None, None]:
    try:
        yield db_session
    finally:
        db_session.rollback()


def _create_builtin_app(
    db_session: Session,
    app_type: ExternalAppType = ExternalAppType.SLACK,
    enabled: bool = True,
) -> ExternalApp:
    return create_external_app__no_commit(
        db_session,
        name=f"{app_type.value} app",
        description="test",
        app_type=app_type,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
        auth_template=dict(_SLACK_AUTH_TEMPLATE),
        organization_credentials={},
        enabled=enabled,
    )


# ── Loader ────────────────────────────────────────────────────────


def test_loader_returns_bundle_for_builtins_and_none_for_custom() -> None:
    slack = get_builtin_external_app_bundle(ExternalAppType.SLACK)
    assert slack is not None
    assert "SKILL.md" in slack
    assert any(p.endswith(".py") for p in slack)  # runnable helper present

    for app_type in (ExternalAppType.LINEAR, ExternalAppType.GOOGLE_CALENDAR):
        bundle = get_builtin_external_app_bundle(app_type)
        assert bundle is not None and "SKILL.md" in bundle

    # CUSTOM apps have no provider and ship no bundle.
    assert get_builtin_external_app_bundle(ExternalAppType.CUSTOM) is None


# ── get_authenticated_builtin_apps_for_user ───────────────────────


def test_authenticated_builtin_app_is_returned(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_skill_auth")
    app = _create_builtin_app(rollback_session)
    upsert_external_app_user_credential__no_commit(
        rollback_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=_FULL_USER_CREDS,
    )

    result = get_authenticated_builtin_apps_for_user(rollback_session, user.id)
    assert [a.id for a in result] == [app.id]


def test_partial_creds_not_authenticated(rollback_session: Session) -> None:
    user = create_test_user(rollback_session, "ea_skill_partial")
    app = _create_builtin_app(rollback_session)
    # Row exists but lacks the required access_token key.
    upsert_external_app_user_credential__no_commit(
        rollback_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={"unrelated": "x"},
    )

    assert get_authenticated_builtin_apps_for_user(rollback_session, user.id) == []


def test_disabled_app_not_returned(rollback_session: Session) -> None:
    user = create_test_user(rollback_session, "ea_skill_disabled")
    app = _create_builtin_app(rollback_session, enabled=False)
    upsert_external_app_user_credential__no_commit(
        rollback_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=_FULL_USER_CREDS,
    )

    assert get_authenticated_builtin_apps_for_user(rollback_session, user.id) == []


def test_custom_app_not_returned_even_when_authenticated(
    rollback_session: Session,
) -> None:
    """CUSTOM has no OAuth provider, so it is not a 'built-in' app and
    must be excluded even with full credentials."""
    user = create_test_user(rollback_session, "ea_skill_custom")
    app = _create_builtin_app(rollback_session, app_type=ExternalAppType.CUSTOM)
    upsert_external_app_user_credential__no_commit(
        rollback_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=_FULL_USER_CREDS,
    )

    assert get_authenticated_builtin_apps_for_user(rollback_session, user.id) == []


# ── Fileset delivery + skills-tab exclusion ───────────────────────


def test_bundle_lands_under_reserved_prefix_not_as_skill(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_skill_fileset")
    app = _create_builtin_app(rollback_session)
    upsert_external_app_user_credential__no_commit(
        rollback_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=_FULL_USER_CREDS,
    )

    apps = get_authenticated_builtin_apps_for_user(rollback_session, user.id)
    files: FileSet = {}
    _merge_external_app_bundles(files, apps)

    expected_dir = f"{_EXTERNAL_APPS_DIR}/{app.id}-slack"
    assert f"{expected_dir}/SKILL.md" in files
    assert f"{expected_dir}/slack_api.py" in files
    # Reserved prefix starts with '_', which the skill slug regex
    # (^[a-z]...) can never produce — so these are structurally not
    # skills and cannot appear in the skills tab.
    assert all(p.startswith(f"{_EXTERNAL_APPS_DIR}/") for p in files)


def test_unauthenticated_user_yields_no_apps_and_no_files(
    rollback_session: Session,
) -> None:
    user = create_test_user(rollback_session, "ea_skill_none")
    _create_builtin_app(rollback_session)  # exists but user not connected

    apps = get_authenticated_builtin_apps_for_user(rollback_session, user.id)
    assert apps == []

    files: FileSet = {}
    _merge_external_app_bundles(files, apps)
    assert files == {}
