from typing import Any

from onyx.configs.app_configs import EXT_APP_SLACK_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_SLACK_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import AdminDescriptorSpec
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.base import OAuthProviderSpec
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.base import OrgCredentialField
from onyx.external_apps.providers.base import parse_granted_scopes


class SlackAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Slack provider."""

    CHANNELS_READ = "slack.channels.read"
    MESSAGES_READ = "slack.messages.read"
    USERS_READ = "slack.users.read"
    SEARCH_READ = "slack.search.read"
    MESSAGES_WRITE = "slack.messages.write"
    DM_OPEN = "slack.dm.open"
    FILES_WRITE = "slack.files.write"


# Slack Web API calls are POST to https://slack.com/api/<method>; the action is
# the method segment of the path.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=SlackAction.CHANNELS_READ,
        normalised_name="View channels & conversations",
        description=(
            "List the workspace's channels and conversations and look up a "
            "single conversation's metadata."
        ),
        matches=(
            RestRoute(method="POST", path="/api/conversations.list"),
            RestRoute(method="POST", path="/api/conversations.info"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=SlackAction.MESSAGES_READ,
        normalised_name="Read messages",
        description=(
            "Read messages and thread replies in a channel or direct message."
        ),
        matches=(
            RestRoute(method="POST", path="/api/conversations.history"),
            RestRoute(method="POST", path="/api/conversations.replies"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=SlackAction.USERS_READ,
        normalised_name="Read users",
        description="List workspace users and look up individual profiles.",
        matches=(
            RestRoute(method="POST", path="/api/users.list"),
            RestRoute(method="POST", path="/api/users.info"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=SlackAction.SEARCH_READ,
        normalised_name="Search messages",
        description="Full-text search across messages the user can see.",
        matches=(RestRoute(method="POST", path="/api/search.messages"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=SlackAction.MESSAGES_WRITE,
        normalised_name="Post a message",
        description="Post a message to a channel or conversation.",
        matches=(RestRoute(method="POST", path="/api/chat.postMessage"),),
    ),
    EndpointSpec(
        id=SlackAction.DM_OPEN,
        normalised_name="Open a direct message",
        description="Open (or resume) a direct message conversation with a user.",
        matches=(RestRoute(method="POST", path="/api/conversations.open"),),
    ),
    EndpointSpec(
        id=SlackAction.FILES_WRITE,
        normalised_name="Upload files",
        description=(
            "Upload a file and share it to a channel, direct message, or "
            "thread using Slack's external upload flow."
        ),
        matches=(
            RestRoute(method="GET", path="/api/files.getUploadURLExternal"),
            RestRoute(method="POST", path="/api/files.getUploadURLExternal"),
            RestRoute(method="POST", path="/api/files.completeUploadExternal"),
            # The raw bytes POST to a pre-signed /upload/v1/<token> URL on
            # files.slack.com — route it to FILES_WRITE, not the domain fallback.
            RestRoute(method="POST", path="/upload/v1/{token...}"),
        ),
    ),
]


class SlackProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.SLACK,
        app_name="Slack",
        oauth=OAuthFlowSpec(
            authorize_url="https://slack.com/oauth/v2/authorize",
            token_url="https://slack.com/api/oauth.v2.access",
            scope=",".join(
                [
                    "channels:history",
                    "channels:read",
                    "chat:write",
                    "files:write",
                    "groups:history",
                    "groups:read",
                    "im:history",
                    "im:read",
                    "im:write",
                    "search:read",
                    "users:read",
                ]
            ),
            scope_param="user_scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read your Slack messages and channels as context inside Onyx Craft."
            ),
            upstream_url_patterns=[
                "https://slack\\.com/api/.*",
                # files.getUploadURLExternal hands back a pre-signed upload URL
                # on the files.slack.com host that the raw bytes are POSTed to.
                "https://files\\.slack\\.com/upload/v1/.*",
            ],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found under your Slack app's Basic Information → "
                        "App Credentials."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found under your Slack app's Basic Information → "
                        "App Credentials. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "Create a Slack app at api.slack.com/apps. Under OAuth & "
                "Permissions, add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) to Redirect URLs, and add the "
                "User Token Scopes you want the agent to use (channels:history, "
                "channels:read, chat:write, files:write, groups:history, "
                "groups:read, im:history, im:read, im:write, search:read, "
                "users:read). No "
                "bot user is required. Then paste the app's Client ID and "
                "Client Secret below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_SLACK_CLIENT_ID,
        "client_secret": EXT_APP_SLACK_CLIENT_SECRET,
    }

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        # Slack v2 with `user_scope` returns the user token nested
        # under `authed_user`; the top-level `access_token` would be
        # the bot token, which we don't request.
        authed_user = response_data.get("authed_user") or {}
        access_token = authed_user.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Slack OAuth response did not contain a user access "
                "token. Make sure the Slack app has user token scopes "
                "configured.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "team_id": (response_data.get("team") or {}).get("id"),
            "team_name": (response_data.get("team") or {}).get("name"),
            "authed_user_id": authed_user.get("id"),
            "scope": authed_user.get("scope"),
        }
        if authed_user.get("refresh_token"):
            creds["refresh_token"] = authed_user["refresh_token"]
        if authed_user.get("expires_in"):
            creds["expires_in"] = authed_user["expires_in"]
        return creds

    def extract_granted_scopes(self, response_data: dict[str, Any]) -> list[str] | None:
        # The user token's granted scopes live under `authed_user.scope` (the
        # top-level `scope` would be the bot's), comma-delimited.
        authed_user = response_data.get("authed_user") or {}
        return parse_granted_scopes(authed_user.get("scope"))
