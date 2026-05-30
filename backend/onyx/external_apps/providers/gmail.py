from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.google_base import GoogleOAuthProvider


# Gmail API v1 (https://gmail.googleapis.com/gmail/v1/users/{userId}/...); the
# action is HTTP method + path. The skill targets `users/me`, but `{userId}`
# matches any single segment so the catalog stays user-agnostic.
class GmailAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Gmail provider."""

    MESSAGES_READ = "gmail.messages.read"
    LABELS_READ = "gmail.labels.read"
    PROFILE_READ = "gmail.profile.read"
    MESSAGES_SEND = "gmail.messages.send"
    MESSAGES_MODIFY = "gmail.messages.modify"
    MESSAGES_TRASH = "gmail.messages.trash"


_USER = "/gmail/v1/users/{userId}"
_MESSAGES = f"{_USER}/messages"
_MESSAGE_ITEM = f"{_USER}/messages/{{messageId}}"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=GmailAction.MESSAGES_READ,
        normalised_name="Read messages",
        description="List or search messages and read a single message.",
        matches=(
            RestRoute(method="GET", path=_MESSAGES),
            RestRoute(method="GET", path=_MESSAGE_ITEM),
        ),
    ),
    EndpointSpec(
        id=GmailAction.LABELS_READ,
        normalised_name="List labels",
        description="List the labels in the mailbox.",
        matches=(RestRoute(method="GET", path=f"{_USER}/labels"),),
    ),
    EndpointSpec(
        id=GmailAction.PROFILE_READ,
        normalised_name="Read profile",
        description="Read the connected account's Gmail profile.",
        matches=(RestRoute(method="GET", path=f"{_USER}/profile"),),
    ),
    EndpointSpec(
        id=GmailAction.MESSAGES_SEND,
        normalised_name="Send a message",
        description="Send an email from the connected account.",
        matches=(RestRoute(method="POST", path=f"{_MESSAGES}/send"),),
    ),
    EndpointSpec(
        id=GmailAction.MESSAGES_MODIFY,
        normalised_name="Modify message labels",
        description="Add or remove labels on a message (mark read, archive, …).",
        matches=(RestRoute(method="POST", path=f"{_MESSAGE_ITEM}/modify"),),
    ),
    EndpointSpec(
        id=GmailAction.MESSAGES_TRASH,
        normalised_name="Trash a message",
        description="Move a message to the trash.",
        matches=(RestRoute(method="POST", path=f"{_MESSAGE_ITEM}/trash"),),
    ),
]


class GmailProvider(GoogleOAuthProvider):
    spec = GoogleOAuthProvider.build_spec(
        app_type=ExternalAppType.GMAIL,
        app_name="Gmail",
        # gmail.modify covers read, send, label, and trash — but not permanent
        # delete, which keeps the integration safer by default.
        scope="https://www.googleapis.com/auth/gmail.modify",
        upstream_url_patterns=["https://gmail\\.googleapis\\.com/gmail/.*"],
        description=(
            "Read, search, and send email from your Gmail account inside Onyx Craft."
        ),
        google_api_name="Gmail API",
        endpoint_catalog=_ENDPOINTS,
    )
