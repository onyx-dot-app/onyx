from typing import Any

import pytest
import requests

from onyx.db.enums import ExternalAppType
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

# Canonical 4-param template: 2 org-supplied, 2 user-supplied.
_AUTH_TEMPLATE: dict[str, str] = {
    "client_id": "{client_id}",
    "client_secret": "{client_secret}",
    "access_token": "Bearer {access_token}",
    "refresh_token": "{refresh_token}",
}
_ORG_CREDENTIALS: dict[str, str] = {
    "client_id": "ORG_CLIENT_ID",
    "client_secret": "ORG_CLIENT_SECRET",
}
_USER_CREDENTIALS: dict[str, str] = {
    "access_token": "USER_ACCESS_TOKEN",
    "refresh_token": "USER_REFRESH_TOKEN",
}
_EXPECTED_USER_KEYS = {"access_token", "refresh_token"}


def _create_test_app(
    admin_user: DATestUser, **overrides: Any
) -> ExternalAppAdminResponse:
    defaults: dict[str, Any] = {
        "name": "Test App",
        "description": "An app for testing",
        "upstream_url_patterns": [r"^https://api\.example\.com/.*$"],
        "auth_template": dict(_AUTH_TEMPLATE),
        "organization_credentials": dict(_ORG_CREDENTIALS),
        "enabled": True,
    }
    defaults.update(overrides)
    return ExternalAppManager.create(
        user_performing_action=admin_user,
        **defaults,
    )


def _assert_user_response_shape_is_safe(
    user_app: ExternalAppUserResponse,
) -> None:
    """Fail loudly if the user-facing payload ever starts leaking admin-only data.

    Runs as a Pydantic model-fields check rather than a dict-keys check so
    a future schema change cannot silently regress the protection.
    """
    # `app_type` is intentionally NOT forbidden — it's the non-sensitive
    # provider discriminator the UI needs and is exposed to users.
    forbidden_fields = {
        "organization_credentials",
        "auth_template",
        "upstream_url_patterns",
        "enabled",
    }
    actual_fields = set(user_app.model_fields.keys())
    leaked = forbidden_fields & actual_fields
    assert not leaked, (
        f"User-facing ExternalAppUserResponse leaked admin-only fields: {leaked}"
    )
    for org_key in _ORG_CREDENTIALS:
        assert org_key not in user_app.credential_keys
        assert org_key not in user_app.credential_values


# ── Happy path ────────────────────────────────────────────────────


def test_admin_creates_app_user_configures_credentials(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    created = _create_test_app(admin_user)
    app_id = created.id

    admin_apps = ExternalAppManager.list_admin(user_performing_action=admin_user)
    assert len(admin_apps) == 1
    admin_app = admin_apps[0]
    assert admin_app.id == app_id
    assert admin_app.name == "Test App"
    assert admin_app.description == "An app for testing"
    assert admin_app.enabled is True
    assert admin_app.upstream_url_patterns == [r"^https://api\.example\.com/.*$"]
    assert admin_app.auth_template == _AUTH_TEMPLATE
    assert admin_app.organization_credentials == _ORG_CREDENTIALS

    user_app_before = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=app_id
    )
    _assert_user_response_shape_is_safe(user_app_before)
    assert user_app_before.name == "Test App"
    assert set(user_app_before.credential_keys) == _EXPECTED_USER_KEYS
    assert user_app_before.credential_values == {}
    assert user_app_before.authenticated is False

    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=app_id,
        credentials=_USER_CREDENTIALS,
    )

    user_app_after = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=app_id
    )
    _assert_user_response_shape_is_safe(user_app_after)
    assert user_app_after.authenticated is True
    assert user_app_after.credential_values == _USER_CREDENTIALS
    assert set(user_app_after.credential_keys) == _EXPECTED_USER_KEYS

    admin_apps_after = ExternalAppManager.list_admin(user_performing_action=admin_user)
    assert admin_apps_after[0].organization_credentials == _ORG_CREDENTIALS


# ── Authorization ─────────────────────────────────────────────────


def test_basic_user_cannot_access_admin_routes(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    created = _create_test_app(admin_user)

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.create(
            user_performing_action=basic_user,
            name="Sneaky App",
            description="should not be created",
            upstream_url_patterns=[],
            auth_template={},
            organization_credentials={},
        )
    assert exc.value.response.status_code in (401, 403)

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.list_admin(user_performing_action=basic_user)
    assert exc.value.response.status_code in (401, 403)

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.update(
            user_performing_action=basic_user,
            app_id=created.id,
            name="Hijacked",
            description="should not be updated",
            upstream_url_patterns=[],
            auth_template={},
            organization_credentials={},
        )
    assert exc.value.response.status_code in (401, 403)

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.delete(user_performing_action=basic_user, app_id=created.id)
    assert exc.value.response.status_code in (401, 403)

    after = ExternalAppManager.list_admin(user_performing_action=admin_user)
    assert len(after) == 1
    assert after[0].name == "Test App"


# ── Delete + recreate ─────────────────────────────────────────────


def test_delete_cascades_user_credentials_and_recreate_yields_fresh_state(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Deleted app's user-credential rows cascade via FK. Recreating
    with the same payload must not resurrect them."""
    first = _create_test_app(admin_user)
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=first.id,
        credentials=_USER_CREDENTIALS,
    )
    assert (
        ExternalAppManager.get_for_user(
            user_performing_action=basic_user, app_id=first.id
        ).authenticated
        is True
    )

    ExternalAppManager.delete(user_performing_action=admin_user, app_id=first.id)
    assert ExternalAppManager.list_for_user(user_performing_action=basic_user) == []

    recreated = _create_test_app(admin_user)
    assert recreated.id != first.id

    user_view = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=recreated.id
    )
    assert user_view.authenticated is False
    assert user_view.credential_values == {}
    assert set(user_view.credential_keys) == _EXPECTED_USER_KEYS


# ── Per-user credential isolation ─────────────────────────────────


def test_user_credentials_are_isolated_between_users(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    # `basic_user` fixture must run first so the next registration is
    # also BASIC, not ADMIN.
    second_basic_user = UserManager.create(name="second_basic_user")

    created = _create_test_app(admin_user)

    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=created.id,
        credentials=_USER_CREDENTIALS,
    )
    second_user_creds = {"access_token": "SECOND_USER_ACCESS_TOKEN"}
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=second_basic_user,
        app_id=created.id,
        credentials=second_user_creds,
    )

    view_1 = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=created.id
    )
    view_2 = ExternalAppManager.get_for_user(
        user_performing_action=second_basic_user, app_id=created.id
    )

    assert view_1.authenticated is True
    assert view_1.credential_values == _USER_CREDENTIALS

    assert view_2.authenticated is False
    assert view_2.credential_values == second_user_creds
    assert view_2.credential_values["access_token"] != _USER_CREDENTIALS["access_token"]


# ── Enable / disable ──────────────────────────────────────────────


def test_disabled_app_hidden_from_users_but_credentials_preserved_on_re_enable(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Disabling hides from the user list but preserves stored
    credentials so re-enabling doesn't force everyone to redo OAuth."""
    created = _create_test_app(admin_user)
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=created.id,
        credentials=_USER_CREDENTIALS,
    )
    assert (
        ExternalAppManager.get_for_user(
            user_performing_action=basic_user, app_id=created.id
        ).authenticated
        is True
    )

    ExternalAppManager.update(
        user_performing_action=admin_user,
        app_id=created.id,
        name=created.name,
        description=created.description,
        upstream_url_patterns=created.upstream_url_patterns,
        auth_template=created.auth_template,
        organization_credentials=created.organization_credentials,
        enabled=False,
    )

    assert ExternalAppManager.list_for_user(user_performing_action=basic_user) == []
    admin_view = ExternalAppManager.list_admin(user_performing_action=admin_user)
    assert len(admin_view) == 1
    assert admin_view[0].enabled is False

    ExternalAppManager.update(
        user_performing_action=admin_user,
        app_id=created.id,
        name=created.name,
        description=created.description,
        upstream_url_patterns=created.upstream_url_patterns,
        auth_template=created.auth_template,
        organization_credentials=created.organization_credentials,
        enabled=True,
    )

    restored = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=created.id
    )
    assert restored.authenticated is True
    assert restored.credential_values == _USER_CREDENTIALS


# ── Auth template reshaping ───────────────────────────────────────


def test_update_app_reshapes_user_credential_keys(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Moving a slot from user-supplied to org-supplied filters the
    stale value out of `credential_values` and shrinks
    `credential_keys` accordingly."""
    created = _create_test_app(admin_user)
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=created.id,
        credentials=_USER_CREDENTIALS,
    )

    new_org_creds = dict(_ORG_CREDENTIALS)
    new_org_creds["access_token"] = "ORG_PROVIDED_ACCESS_TOKEN"

    ExternalAppManager.update(
        user_performing_action=admin_user,
        app_id=created.id,
        name=created.name,
        description=created.description,
        upstream_url_patterns=created.upstream_url_patterns,
        auth_template=created.auth_template,
        organization_credentials=new_org_creds,
        enabled=True,
    )

    user_view = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=created.id
    )

    assert user_view.credential_keys == ["refresh_token"]
    assert user_view.credential_values == {
        "refresh_token": _USER_CREDENTIALS["refresh_token"],
    }
    assert user_view.authenticated is True


# ── Negative paths ────────────────────────────────────────────────


def test_update_or_delete_nonexistent_app_returns_404(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    missing_id = 999_999

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.update(
            user_performing_action=admin_user,
            app_id=missing_id,
            name="x",
            description="x",
            upstream_url_patterns=[],
            auth_template={},
            organization_credentials={},
        )
    assert exc.value.response.status_code == 404

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.delete(user_performing_action=admin_user, app_id=missing_id)
    assert exc.value.response.status_code == 404

    with pytest.raises(requests.exceptions.HTTPError) as exc:
        ExternalAppManager.upsert_user_credentials(
            user_performing_action=admin_user,
            app_id=missing_id,
            credentials={"any": "value"},
        )
    assert exc.value.response.status_code == 404


# ── Authentication thresholds ─────────────────────────────────────


def test_partial_credentials_keep_app_unauthenticated_full_org_template_is_immediately_authenticated(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Partial creds → not authenticated. Fully-org-covered template
    → authenticated with empty credential_keys."""
    partial_app = _create_test_app(admin_user, name="Partial App")
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=partial_app.id,
        credentials={"access_token": "USER_ACCESS_TOKEN"},
    )
    partial_view = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=partial_app.id
    )
    assert partial_view.authenticated is False
    assert partial_view.credential_values == {
        "access_token": "USER_ACCESS_TOKEN",
    }
    assert set(partial_view.credential_keys) == _EXPECTED_USER_KEYS

    fully_org_org_creds = {
        "client_id": "ORG_CLIENT_ID",
        "client_secret": "ORG_CLIENT_SECRET",
        "access_token": "ORG_ACCESS_TOKEN",
        "refresh_token": "ORG_REFRESH_TOKEN",
    }
    org_only_app = _create_test_app(
        admin_user,
        name="Org-only App",
        organization_credentials=fully_org_org_creds,
    )
    org_only_view = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=org_only_app.id
    )
    assert org_only_view.credential_keys == []
    assert org_only_view.credential_values == {}
    assert org_only_view.authenticated is True


# ── app_type ──────────────────────────────────────────────────────


def test_app_type_round_trips_and_defaults_to_custom(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    default_app = _create_test_app(admin_user, name="Default-type App")
    assert default_app.app_type == ExternalAppType.CUSTOM

    slack_app = _create_test_app(
        admin_user, name="Slack App", app_type=ExternalAppType.SLACK
    )
    assert slack_app.app_type == ExternalAppType.SLACK

    updated = ExternalAppManager.update(
        user_performing_action=admin_user,
        app_id=slack_app.id,
        name=slack_app.name,
        description=slack_app.description,
        upstream_url_patterns=slack_app.upstream_url_patterns,
        auth_template=slack_app.auth_template,
        organization_credentials=slack_app.organization_credentials,
        enabled=slack_app.enabled,
        app_type=ExternalAppType.LINEAR,
    )
    assert updated.app_type == ExternalAppType.LINEAR
