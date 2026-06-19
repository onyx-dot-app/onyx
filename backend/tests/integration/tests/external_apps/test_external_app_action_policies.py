"""Integration coverage for the admin action-policy lifecycle on built-in
external apps, exercised end-to-end through the ``/admin/apps`` API via
``ExternalAppManager`` (real deployment, real auth, no direct DB access).

Contract under test (observed through the admin response's ``actions`` view):

- a created built-in app returns its full action catalog — supplied policies
  honoured, everything else falling back to each action's declared
  ``default_policy`` (Slack reads default to ``ALWAYS``, the write to ``ASK``);
- a supplied map merges over the stored set: named actions update, unmentioned
  ones keep their value, and the full action set is unchanged;
- an omitted map (``None`` — e.g. an enable toggle / rename) preserves choices;
- clearing an override means sending that action explicitly as ``ASK``.
"""

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.slack import SlackAction
from onyx.server.features.build.external_apps.models import ExternalAppAdminResponse
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.test_models import DATestUser

_SLACK_AUTH = {"Authorization": "Bearer {access_token}"}
_SLACK_URLS = [r"^https://slack\.com/api/.*$"]


def _create_slack(
    admin_user: DATestUser,
    action_policies: dict[str, EndpointPolicy] | None = None,
) -> ExternalAppAdminResponse:
    return ExternalAppManager.create(
        user_performing_action=admin_user,
        name="Slack",
        description="Slack",
        upstream_url_patterns=list(_SLACK_URLS),
        auth_template=dict(_SLACK_AUTH),
        organization_credentials={},
        app_type=ExternalAppType.SLACK,
        action_policies=action_policies,
    )


def _update_slack(
    admin_user: DATestUser,
    app_id: int,
    action_policies: dict[str, EndpointPolicy] | None,
) -> ExternalAppAdminResponse:
    return ExternalAppManager.update(
        user_performing_action=admin_user,
        app_id=app_id,
        name="Slack",
        description="Slack",
        upstream_url_patterns=list(_SLACK_URLS),
        auth_template=dict(_SLACK_AUTH),
        organization_credentials={},
        app_type=ExternalAppType.SLACK,
        action_policies=action_policies,
    )


def _states(resp: ExternalAppAdminResponse) -> dict[str, EndpointPolicy]:
    return {action.action_id: action.state for action in resp.actions}


def _fetch_states(admin_user: DATestUser, app_id: int) -> dict[str, EndpointPolicy]:
    """Re-read via the list endpoint, so assertions reflect persisted state, not
    just the create/update echo."""
    apps = ExternalAppManager.list_admin(user_performing_action=admin_user)
    app = next(a for a in apps if a.id == app_id)
    return _states(app)


def test_create_returns_full_catalog_with_overrides(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    created = _create_slack(
        admin_user,
        action_policies={
            SlackAction.MESSAGES_READ: EndpointPolicy.ALWAYS,
            SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY,
        },
    )

    states = _states(created)
    # Overrides honoured; unset catalog actions fall back to their declared
    # default (Slack reads default to ALWAYS).
    assert states[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    assert states[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.USERS_READ.value] == EndpointPolicy.ALWAYS
    # The same set persists across a fresh read.
    assert _fetch_states(admin_user, created.id) == states


def test_create_without_policies_yields_action_defaults(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    created = _create_slack(admin_user)

    states = _states(created)
    assert states  # the catalog is non-empty
    # No supplied policies → each action falls back to its declared default:
    # reads auto-approve (ALWAYS), the write requires approval (ASK).
    assert states[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.USERS_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.SEARCH_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.ASK
    assert _fetch_states(admin_user, created.id) == states


def test_edit_merges_overrides_preserving_unmentioned(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    created = _create_slack(
        admin_user,
        action_policies={
            SlackAction.MESSAGES_READ: EndpointPolicy.ALWAYS,
            SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY,
        },
    )

    # A partial map updates only the named action; the rest keep their value.
    edited = _update_slack(
        admin_user,
        created.id,
        action_policies={SlackAction.CHANNELS_READ: EndpointPolicy.ALWAYS},
    )

    states = _states(edited)
    assert states[SlackAction.CHANNELS_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert states[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    # The full action set is unchanged by the edit (no policy dropped or added).
    assert set(states) == set(_states(created))
    assert _fetch_states(admin_user, created.id) == states


def test_edit_omitting_policies_preserves_existing(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    created = _create_slack(
        admin_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    # An edit that omits action_policies (e.g. an enable toggle / rename) must
    # not wipe the admin's stored choices.
    _update_slack(admin_user, created.id, action_policies=None)

    states = _fetch_states(admin_user, created.id)
    assert states[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY


def test_edit_with_explicit_ask_clears_override(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    created = _create_slack(
        admin_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    # Clearing an override means naming the action explicitly as ASK.
    edited = _update_slack(
        admin_user,
        created.id,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.ASK},
    )

    assert _states(edited)[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.ASK


def test_patch_sets_enablement_and_policies(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """The narrow PATCH endpoint (keyed only by id) toggles enablement and
    merges policies the same way the upsert path does."""
    created = _create_slack(admin_user)
    assert created.enabled is True

    patched = ExternalAppManager.set_enablement(
        user_performing_action=admin_user,
        app_id=created.id,
        enabled=False,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    assert patched.enabled is False
    states = _states(patched)
    assert states[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
    # Unmentioned actions keep their declared default.
    assert states[SlackAction.MESSAGES_READ.value] == EndpointPolicy.ALWAYS
    assert _fetch_states(admin_user, created.id) == states


def test_patch_omitting_policies_preserves_existing(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """A bare enable/disable PATCH (no action_policies) must not clobber the
    admin's stored choices."""
    created = _create_slack(
        admin_user,
        action_policies={SlackAction.MESSAGES_WRITE: EndpointPolicy.DENY},
    )

    ExternalAppManager.set_enablement(
        user_performing_action=admin_user,
        app_id=created.id,
        enabled=False,
        action_policies=None,
    )

    states = _fetch_states(admin_user, created.id)
    assert states[SlackAction.MESSAGES_WRITE.value] == EndpointPolicy.DENY
