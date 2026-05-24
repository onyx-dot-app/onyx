from typing import Any

import httpx
import pytest

from onyx.db.enums import ExternalAppType
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

# A canonical auth template used across most tests: four credential slots
# where the org pre-fills two (client_id, client_secret) and the user
# must fill the remaining two (access_token, refresh_token).
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
    """Create the canonical 4-param test app, with any field overridable.

    Default shape: 2 org-supplied credentials, 2 user-supplied. Overrides
    let individual tests vary one field (e.g. `enabled=False`) without
    repeating the whole arg list.
    """
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


# =============================================================================
# Happy path
# =============================================================================


def test_admin_creates_app_user_configures_credentials(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """End-to-end: admin sets up a 4-param app (2 org / 2 user), basic user
    fills in their half, and ends up authenticated. Verifies the user
    surface never exposes admin-only data along the way."""
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


# =============================================================================
# Authorization boundary
# =============================================================================


def test_basic_user_cannot_access_admin_routes(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Non-admins must be blocked from every /admin/apps verb. Creating,
    listing, updating, and deleting are all admin-only — and the test
    proves the gate by checking each verb independently rather than
    inferring from a single call."""
    # Admin sets up a real app for the basic user to *attempt* to mutate.
    created = _create_test_app(admin_user)

    # POST (create) as basic user → forbidden
    with pytest.raises(httpx.HTTPStatusError) as exc:
        ExternalAppManager.create(
            user_performing_action=basic_user,
            name="Sneaky App",
            description="should not be created",
            upstream_url_patterns=[],
            auth_template={},
            organization_credentials={},
        )
    assert exc.value.response.status_code in (401, 403)

    # GET admin list as basic user → forbidden
    with pytest.raises(httpx.HTTPStatusError) as exc:
        ExternalAppManager.list_admin(user_performing_action=basic_user)
    assert exc.value.response.status_code in (401, 403)

    # POST (update existing) as basic user → forbidden
    with pytest.raises(httpx.HTTPStatusError) as exc:
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

    # DELETE as basic user → forbidden
    with pytest.raises(httpx.HTTPStatusError) as exc:
        ExternalAppManager.delete(user_performing_action=basic_user, app_id=created.id)
    assert exc.value.response.status_code in (401, 403)

    # And the app the admin created should still exist, untouched.
    after = ExternalAppManager.list_admin(user_performing_action=admin_user)
    assert len(after) == 1
    assert after[0].name == "Test App"


# =============================================================================
# Delete + recreate
# =============================================================================


def test_delete_cascades_user_credentials_and_recreate_yields_fresh_state(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Deleting an app must wipe every user's stored credentials for it
    (FK ON DELETE CASCADE), and re-creating an app with the same payload
    produces a brand-new id with no resurrected credentials. This is the
    only safe behavior — otherwise old creds could re-attach to a fresh
    "app" the admin thinks they're starting from scratch.
    """
    # First lifecycle: create + user authenticates.
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

    # Admin deletes the app.
    ExternalAppManager.delete(user_performing_action=admin_user, app_id=first.id)

    # User can no longer see the app.
    user_list_after_delete = ExternalAppManager.list_for_user(
        user_performing_action=basic_user
    )
    assert user_list_after_delete == []

    # Admin re-creates an app with identical fields.
    recreated = _create_test_app(admin_user)
    # New row → new id (Postgres SERIAL doesn't recycle by default, but
    # even if it did, what matters is that the row is logically distinct).
    assert recreated.id != first.id

    # The re-created app shows up for the user — *unauthenticated*. If
    # credentials had resurrected from the deleted row, this would fail.
    user_view = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=recreated.id
    )
    assert user_view.authenticated is False
    assert user_view.credential_values == {}
    assert set(user_view.credential_keys) == _EXPECTED_USER_KEYS


# =============================================================================
# Per-user credential isolation
# =============================================================================


def test_user_credentials_are_isolated_between_users(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Two basic users configure different credentials for the same app.
    Each user must see only their own values, and one user's
    `authenticated` state must not influence the other's."""
    # `basic_user` fixture must run before any UserManager.create() so the
    # first user got the BASIC role; subsequent registrations are also BASIC.
    second_basic_user = UserManager.create(name="second_basic_user")

    created = _create_test_app(admin_user)

    # User 1 authenticates fully.
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=created.id,
        credentials=_USER_CREDENTIALS,
    )
    # User 2 stores only one of the two required values.
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

    # User 1: fully authenticated, sees their own values.
    assert view_1.authenticated is True
    assert view_1.credential_values == _USER_CREDENTIALS

    # User 2: not authenticated (missing refresh_token), sees only their value.
    assert view_2.authenticated is False
    assert view_2.credential_values == second_user_creds
    # And critically — user 2 does not see user 1's access_token value.
    assert view_2.credential_values["access_token"] != _USER_CREDENTIALS["access_token"]


# =============================================================================
# Enable / disable kill switch
# =============================================================================


def test_disabled_app_hidden_from_users_but_credentials_preserved_on_re_enable(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Disabling an app makes it disappear from the user list (kill
    switch for the proxy), but the user's stored credentials must
    survive the disable so re-enabling restores them automatically.
    Otherwise admins would have to coordinate "redo your OAuth dance"
    with every user every time they temporarily disable an integration.
    """
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

    # Admin disables the app.
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

    # User no longer sees the app at all.
    assert ExternalAppManager.list_for_user(user_performing_action=basic_user) == []
    # But admin still sees it, with enabled=False.
    admin_view = ExternalAppManager.list_admin(user_performing_action=admin_user)
    assert len(admin_view) == 1
    assert admin_view[0].enabled is False

    # Admin re-enables.
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

    # The user's previously-stored credentials must still be there.
    restored = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=created.id
    )
    assert restored.authenticated is True
    assert restored.credential_values == _USER_CREDENTIALS


# =============================================================================
# Auth template reshaping
# =============================================================================


def test_update_app_reshapes_user_credential_keys(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """When an admin moves a credential slot from user-supplied to
    org-supplied (or vice versa), the user-facing `credential_keys`
    should follow. Stale values the user had stored for a now-removed
    key should be filtered out of `credential_values` so the frontend
    never renders a field that no longer applies."""
    created = _create_test_app(admin_user)
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=created.id,
        credentials=_USER_CREDENTIALS,
    )

    # Admin moves `access_token` into the org credentials — now the user
    # is only responsible for `refresh_token`.
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

    # Required keys shrank to just refresh_token.
    assert user_view.credential_keys == ["refresh_token"]
    # User's stale access_token is filtered out — frontend will not see it.
    assert user_view.credential_values == {
        "refresh_token": _USER_CREDENTIALS["refresh_token"],
    }
    # Still authenticated because refresh_token (the only remaining key) is set.
    assert user_view.authenticated is True


# =============================================================================
# Negative paths
# =============================================================================


def test_update_or_delete_nonexistent_app_returns_404(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """The admin routes must distinguish "id you supplied doesn't exist"
    from "your inputs were bad" — admins relying on idempotent retries
    need a 404 to differentiate `id=stale` from `name=invalid`."""
    missing_id = 999_999

    with pytest.raises(httpx.HTTPStatusError) as exc:
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

    with pytest.raises(httpx.HTTPStatusError) as exc:
        ExternalAppManager.delete(user_performing_action=admin_user, app_id=missing_id)
    assert exc.value.response.status_code == 404

    # Posting credentials against a non-existent app must also 404 — the
    # check is in the same place as the admin flow for consistency.
    with pytest.raises(httpx.HTTPStatusError) as exc:
        ExternalAppManager.upsert_user_credentials(
            user_performing_action=admin_user,
            app_id=missing_id,
            credentials={"any": "value"},
        )
    assert exc.value.response.status_code == 404


# =============================================================================
# Authentication thresholds
# =============================================================================


def test_partial_credentials_keep_app_unauthenticated_full_org_template_is_immediately_authenticated(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
) -> None:
    """Two complementary boundary cases:

    1. Filling some-but-not-all required keys must leave `authenticated`
       False — partial creds are a half-finished setup, not a green
       light for the proxy.
    2. An app whose auth_template is fully covered by org credentials has
       *no* user-required keys, and so should be immediately authenticated
       for every user with no action required. This is the convenience
       case where an integration uses shared org credentials only.
    """
    # Case 1: partial credentials → not authenticated.
    partial_app = _create_test_app(admin_user, name="Partial App")
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=partial_app.id,
        credentials={"access_token": "USER_ACCESS_TOKEN"},  # missing refresh_token
    )
    partial_view = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=partial_app.id
    )
    assert partial_view.authenticated is False
    assert partial_view.credential_values == {
        "access_token": "USER_ACCESS_TOKEN",
    }
    assert set(partial_view.credential_keys) == _EXPECTED_USER_KEYS

    # Case 2: fully-org-covered template → immediately authenticated.
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


# =============================================================================
# app_type plumbing
# =============================================================================


def test_app_type_defaults_to_custom_and_is_immutable_on_update(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """`app_type` is the discriminator the OAuth dispatch layer keys off and
    what the backing skill's definition source is bound to, so it's fixed at
    creation. The default flow (the manager's `create()` with no override)
    produces a CUSTOM app, an explicit built-in value (SLACK) round-trips on
    create, and an update that re-sends the *same* type succeeds — but an
    update that tries to *change* the type is rejected with 400 rather than
    silently rebinding the skill and orphaning credentials."""
    default_app = _create_test_app(admin_user, name="Default-type App")
    assert default_app.app_type == ExternalAppType.CUSTOM

    slack_app = _create_test_app(
        admin_user, name="Slack App", app_type=ExternalAppType.SLACK
    )
    assert slack_app.app_type == ExternalAppType.SLACK

    # Re-sending the unchanged app_type is a valid update (validation passes
    # because old == new), and other fields still mutate.
    unchanged = ExternalAppManager.update(
        user_performing_action=admin_user,
        app_id=slack_app.id,
        name="Slack App (renamed)",
        description=slack_app.description,
        upstream_url_patterns=slack_app.upstream_url_patterns,
        auth_template=slack_app.auth_template,
        organization_credentials=slack_app.organization_credentials,
        enabled=slack_app.enabled,
        app_type=ExternalAppType.SLACK,
    )
    assert unchanged.app_type == ExternalAppType.SLACK
    assert unchanged.name == "Slack App (renamed)"

    # Changing app_type is forbidden.
    with pytest.raises(httpx.HTTPStatusError) as exc:
        ExternalAppManager.update(
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
    assert exc.value.response.status_code == 400

    # The stored type is unchanged after the rejected update.
    apps = ExternalAppManager.list_admin(admin_user)
    persisted = next(a for a in apps if a.id == slack_app.id)
    assert persisted.app_type == ExternalAppType.SLACK
