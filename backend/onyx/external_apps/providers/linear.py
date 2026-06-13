from typing import Any

from onyx.configs.app_configs import EXT_APP_LINEAR_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_LINEAR_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import GraphQLOp
from onyx.external_apps.providers.base import AdminDescriptorSpec
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.base import OAuthProviderSpec
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.base import OrgCredentialField


class LinearAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Linear provider."""

    VIEWER_READ = "linear.viewer.read"
    TEAMS_READ = "linear.teams.read"
    ISSUES_READ = "linear.issues.read"
    PROJECTS_READ = "linear.projects.read"
    ISSUES_CREATE = "linear.issues.create"
    COMMENTS_CREATE = "linear.comments.create"
    PROJECTS_CREATE = "linear.projects.create"
    PROJECTS_UPDATE = "linear.projects.update"


# Linear is a single GraphQL endpoint (POST https://api.linear.app/graphql); the
# action is the root field of the operation in the request body.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=LinearAction.VIEWER_READ,
        normalised_name="Read the connected user",
        description="Read the authenticated user's profile (viewer).",
        matches=(GraphQLOp(operation_type="query", field="viewer"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=LinearAction.TEAMS_READ,
        normalised_name="Read teams",
        description="List the workspace's teams.",
        matches=(GraphQLOp(operation_type="query", field="teams"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=LinearAction.ISSUES_READ,
        normalised_name="Read issues",
        description="List, fetch, and search issues.",
        matches=(
            GraphQLOp(operation_type="query", field="issues"),
            GraphQLOp(operation_type="query", field="issue"),
            GraphQLOp(operation_type="query", field="issueSearch"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=LinearAction.PROJECTS_READ,
        normalised_name="Read projects",
        description="List projects.",
        matches=(GraphQLOp(operation_type="query", field="projects"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=LinearAction.ISSUES_CREATE,
        normalised_name="Create an issue",
        description="Create a new issue.",
        matches=(GraphQLOp(operation_type="mutation", field="issueCreate"),),
    ),
    EndpointSpec(
        id=LinearAction.COMMENTS_CREATE,
        normalised_name="Comment on an issue",
        description="Add a comment to an issue.",
        matches=(GraphQLOp(operation_type="mutation", field="commentCreate"),),
    ),
    EndpointSpec(
        id=LinearAction.PROJECTS_CREATE,
        normalised_name="Create a project",
        description="Create a new project.",
        matches=(GraphQLOp(operation_type="mutation", field="projectCreate"),),
    ),
    EndpointSpec(
        id=LinearAction.PROJECTS_UPDATE,
        normalised_name="Edit a project",
        description="Update an existing project.",
        matches=(GraphQLOp(operation_type="mutation", field="projectUpdate"),),
    ),
]


class LinearProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.LINEAR,
        app_name="Linear",
        oauth=OAuthFlowSpec(
            authorize_url="https://linear.app/oauth/authorize",
            token_url="https://api.linear.app/oauth/token",
            scope="read,write",
            scope_param="scope",
            # actor=user is Linear's default but explicit — actor=application
            # would mint an app-acting token instead of user-acting.
            extra_authorize_params={
                "response_type": "code",
                "actor": "user",
            },
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read and create issues, projects, and comments in Linear "
                "on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.linear\\.app/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found in Linear → Settings → API → OAuth "
                        "applications → your app."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found alongside the Client ID. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In Linear: Settings → API → OAuth applications → New OAuth "
                "application. Fill in name, developer email, and description. "
                "Add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) to Callback URLs. Save. Then "
                "paste the Client ID and Client Secret below. The agent will "
                "be granted read+write access to issues, projects, and comments."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_LINEAR_CLIENT_ID,
        "client_secret": EXT_APP_LINEAR_CLIENT_SECRET,
    }

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Linear OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "scope": response_data.get("scope"),
            "token_type": response_data.get("token_type"),
        }
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
