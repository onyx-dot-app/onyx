from collections.abc import Mapping

from onyx.configs.app_configs import EXT_APP_GMAIL_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_GMAIL_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.presentation.payload_decoders import GmailRawMimeDecoder
from onyx.external_apps.presentation.payload_decoders import PayloadDecoder
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import OnyxManagedExtApp
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
    THREADS_READ = "gmail.threads.read"
    ATTACHMENTS_READ = "gmail.attachments.read"
    DRAFTS_READ = "gmail.drafts.read"
    DRAFTS_CREATE = "gmail.drafts.create"
    DRAFTS_UPDATE = "gmail.drafts.update"
    DRAFTS_DELETE = "gmail.drafts.delete"
    DRAFTS_SEND = "gmail.drafts.send"


_USER = "/gmail/v1/users/{userId}"
_MESSAGES = f"{_USER}/messages"
_MESSAGE_ITEM = f"{_USER}/messages/{{messageId}}"
_THREADS = f"{_USER}/threads"
_THREAD_ITEM = f"{_USER}/threads/{{threadId}}"
_DRAFTS = f"{_USER}/drafts"
_DRAFT_ITEM = f"{_USER}/drafts/{{draftId}}"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=GmailAction.MESSAGES_READ,
        normalised_name="Read messages",
        description="List or search messages and read a single message.",
        matches=(
            RestRoute(method="GET", path=_MESSAGES),
            RestRoute(method="GET", path=_MESSAGE_ITEM),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.LABELS_READ,
        normalised_name="List labels",
        description="List the labels in the mailbox.",
        matches=(RestRoute(method="GET", path=f"{_USER}/labels"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.PROFILE_READ,
        normalised_name="Read profile",
        description="Read the connected account's Gmail profile.",
        matches=(RestRoute(method="GET", path=f"{_USER}/profile"),),
        default_policy=EndpointPolicy.ALWAYS,
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
    EndpointSpec(
        id=GmailAction.THREADS_READ,
        normalised_name="Read threads",
        description="List threads and read a single conversation thread.",
        matches=(
            RestRoute(method="GET", path=_THREADS),
            RestRoute(method="GET", path=_THREAD_ITEM),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.ATTACHMENTS_READ,
        normalised_name="Read attachments",
        description="Download an attachment from a message.",
        matches=(
            RestRoute(
                method="GET", path=f"{_MESSAGE_ITEM}/attachments/{{attachmentId}}"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.DRAFTS_READ,
        normalised_name="Read drafts",
        description="List drafts and read a single draft.",
        matches=(
            RestRoute(method="GET", path=_DRAFTS),
            RestRoute(method="GET", path=_DRAFT_ITEM),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.DRAFTS_CREATE,
        normalised_name="Create a draft",
        # Drafts aren't sent, so creating one is a safe place for the agent to
        # prepare an email for the user to review and send from Gmail.
        description="Save a new draft email (not sent).",
        matches=(RestRoute(method="POST", path=_DRAFTS),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.DRAFTS_UPDATE,
        normalised_name="Update a draft",
        description="Replace the contents of an existing draft (not sent).",
        matches=(RestRoute(method="PUT", path=_DRAFT_ITEM),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GmailAction.DRAFTS_DELETE,
        normalised_name="Delete a draft",
        description="Permanently delete a draft.",
        matches=(RestRoute(method="DELETE", path=_DRAFT_ITEM),),
    ),
    EndpointSpec(
        id=GmailAction.DRAFTS_SEND,
        normalised_name="Send a draft",
        description="Send an existing draft as an email.",
        matches=(RestRoute(method="POST", path=f"{_DRAFTS}/send"),),
    ),
]


class GmailProvider(GoogleOAuthProvider, OnyxManagedExtApp):
    spec = GoogleOAuthProvider.build_spec(
        app_type=ExternalAppType.GMAIL,
        app_name="Gmail",
        # gmail.modify covers read, send, label, trash, threads, attachments, and
        # the full draft lifecycle — but not permanent message delete, which keeps
        # the integration safer by default.
        scope="https://www.googleapis.com/auth/gmail.modify",
        upstream_url_patterns=["https://gmail\\.googleapis\\.com/gmail/.*"],
        description=(
            "Read, search, send, and draft email from your Gmail account inside "
            "Onyx Craft."
        ),
        google_api_name="Gmail API",
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_GMAIL_CLIENT_ID,
        "client_secret": EXT_APP_GMAIL_CLIENT_SECRET,
    }

    # base64url MIME bodies decoded for the approval card. `messages.send` holds
    # `raw` top-level; draft create/update nest it under `message`.
    _PAYLOAD_DECODERS: Mapping[str, PayloadDecoder] = {
        GmailAction.MESSAGES_SEND: GmailRawMimeDecoder(),
        GmailAction.DRAFTS_CREATE: GmailRawMimeDecoder(wrapper_key="message"),
        GmailAction.DRAFTS_UPDATE: GmailRawMimeDecoder(wrapper_key="message"),
    }

    def payload_decoders(self) -> Mapping[str, PayloadDecoder]:
        return self._PAYLOAD_DECODERS
