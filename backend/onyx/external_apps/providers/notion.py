import base64
from typing import Any

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
from onyx.external_apps.providers.base import OrgCredentialField
from onyx.external_apps.providers.base import TokenExchangeRequest

# Pinned across the provider and the sandbox skill so request-shaping stays
# consistent with what the OAuth exchange negotiated.
_NOTION_VERSION = "2022-06-28"


class NotionAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Notion provider."""

    USERS_READ = "notion.users.read"
    SEARCH = "notion.search"
    PAGES_READ = "notion.pages.read"
    BLOCKS_READ = "notion.blocks.read"
    DATABASES_READ = "notion.databases.read"
    DATABASES_QUERY = "notion.databases.query"
    COMMENTS_READ = "notion.comments.read"
    PAGES_CREATE = "notion.pages.create"
    PAGES_UPDATE = "notion.pages.update"
    BLOCKS_APPEND = "notion.blocks.append"
    BLOCKS_UPDATE = "notion.blocks.update"
    BLOCKS_DELETE = "notion.blocks.delete"
    DATABASES_CREATE = "notion.databases.create"
    DATABASES_UPDATE = "notion.databases.update"
    COMMENTS_CREATE = "notion.comments.create"


# Notion's REST API is a path-addressed JSON API rooted at
# https://api.notion.com; the action is the HTTP method + path template
# (including the `/v1` version prefix). A `{name}` segment matches one path
# segment (a page / block / database id). Search and database-query are reads
# even though they're POSTs — Notion models "query" as a POST body.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=NotionAction.USERS_READ,
        normalised_name="Read users",
        description=(
            "List the workspace's users and fetch a single user (including the "
            "authenticated bot via /users/me)."
        ),
        matches=(
            RestRoute(method="GET", path="/v1/users"),
            RestRoute(method="GET", path="/v1/users/{user_id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.SEARCH,
        normalised_name="Search",
        description="Search all pages and databases the integration can access.",
        matches=(RestRoute(method="POST", path="/v1/search"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.PAGES_READ,
        normalised_name="Read pages",
        description="Fetch a page's properties and read an individual page property.",
        matches=(
            RestRoute(method="GET", path="/v1/pages/{page_id}"),
            RestRoute(
                method="GET", path="/v1/pages/{page_id}/properties/{property_id}"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.BLOCKS_READ,
        normalised_name="Read blocks",
        description="Fetch a block and list a block's (or page's) child blocks.",
        matches=(
            RestRoute(method="GET", path="/v1/blocks/{block_id}"),
            RestRoute(method="GET", path="/v1/blocks/{block_id}/children"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.DATABASES_READ,
        normalised_name="Read databases",
        description="Fetch a database's schema and metadata.",
        matches=(RestRoute(method="GET", path="/v1/databases/{database_id}"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.DATABASES_QUERY,
        normalised_name="Query a database",
        description="Query a database's rows with optional filters and sorts.",
        matches=(
            RestRoute(method="POST", path="/v1/databases/{database_id}/query"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.COMMENTS_READ,
        normalised_name="Read comments",
        description="List the unresolved comments on a page or block.",
        matches=(RestRoute(method="GET", path="/v1/comments"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=NotionAction.PAGES_CREATE,
        normalised_name="Create a page",
        description="Create a new page under a page or database parent.",
        matches=(RestRoute(method="POST", path="/v1/pages"),),
    ),
    EndpointSpec(
        id=NotionAction.PAGES_UPDATE,
        normalised_name="Update a page",
        description="Update a page's properties, icon, cover, or archive it.",
        matches=(RestRoute(method="PATCH", path="/v1/pages/{page_id}"),),
    ),
    EndpointSpec(
        id=NotionAction.BLOCKS_APPEND,
        normalised_name="Append blocks",
        description="Append child blocks (content) to a page or block.",
        matches=(RestRoute(method="PATCH", path="/v1/blocks/{block_id}/children"),),
    ),
    EndpointSpec(
        id=NotionAction.BLOCKS_UPDATE,
        normalised_name="Update a block",
        description="Update or archive an individual block's content.",
        matches=(RestRoute(method="PATCH", path="/v1/blocks/{block_id}"),),
    ),
    EndpointSpec(
        id=NotionAction.BLOCKS_DELETE,
        normalised_name="Delete a block",
        description="Delete (move to trash) an individual block.",
        matches=(RestRoute(method="DELETE", path="/v1/blocks/{block_id}"),),
    ),
    EndpointSpec(
        id=NotionAction.DATABASES_CREATE,
        normalised_name="Create a database",
        description="Create a new database under a page parent.",
        matches=(RestRoute(method="POST", path="/v1/databases"),),
    ),
    EndpointSpec(
        id=NotionAction.DATABASES_UPDATE,
        normalised_name="Update a database",
        description="Update a database's title, description, or schema.",
        matches=(RestRoute(method="PATCH", path="/v1/databases/{database_id}"),),
    ),
    EndpointSpec(
        id=NotionAction.COMMENTS_CREATE,
        normalised_name="Add a comment",
        description="Add a comment to a page or an existing discussion.",
        matches=(RestRoute(method="POST", path="/v1/comments"),),
    ),
]


class NotionProvider(OAuthExternalAppProvider):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.NOTION,
        app_name="Notion",
        oauth=OAuthFlowSpec(
            authorize_url="https://api.notion.com/v1/oauth/authorize",
            token_url="https://api.notion.com/v1/oauth/token",
            # Notion doesn't use OAuth scopes — an integration's capabilities are
            # configured on its settings page, not requested per-authorization.
            scope="",
            scope_param="scope",
            # `owner=user` is required by Notion's public OAuth flow so the
            # authorization is granted on behalf of the connecting user.
            extra_authorize_params={
                "response_type": "code",
                "owner": "user",
            },
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Search, read, and write Notion pages, databases, blocks, and "
                "comments on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.notion\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your Notion integration's settings page "
                        "(notion.so/my-integrations → your integration → OAuth "
                        "Domain & URIs)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Generated on the same integration settings page under "
                        "OAuth secrets. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In Notion: notion.so/my-integrations → New integration → set "
                "type to Public. Under OAuth Domain & URIs, add this Onyx "
                "instance's callback URL (/craft/v1/apps/oauth/callback) as a "
                "Redirect URI. Configure the integration's capabilities (read "
                "and/or write content). Save, then copy the OAuth Client ID and "
                "Client Secret and paste them below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    def build_token_exchange_request(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> TokenExchangeRequest:
        # Notion requires HTTP Basic client authentication and a JSON body for
        # the token exchange (client_id/client_secret are NOT accepted in the
        # form body), so override the default RFC-6749 form-encoded request.
        basic = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")
        return TokenExchangeRequest(
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Notion-Version": _NOTION_VERSION,
            },
            json_body={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Notion OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {"access_token": access_token}
        # Notion bot tokens don't expire and carry no refresh token, so persist
        # only the workspace/bot metadata that's actually present — handy for
        # display and never assumed to exist.
        for key in (
            "token_type",
            "bot_id",
            "workspace_id",
            "workspace_name",
            "workspace_icon",
            "owner",
            "duplicated_template_id",
        ):
            value = response_data.get(key)
            if value is not None:
                creds[key] = value
        return creds
