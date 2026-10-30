"""Gateway and context builders that the Outlook capability check tests share."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import CapabilityCheckContext
from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo
from onyx.connectors.outlook.models import (
    OutlookDeltaPage,
    OutlookFolderPage,
    OutlookMailboxPage,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    CREDENTIALS,
    folder,
    mailbox,
    message,
)


def healthy_gateway() -> MagicMock:
    """A healthy tenant: one user with a readable mailbox holding one message."""
    gateway = create_autospec(OutlookSourceOperations, instance=True)
    gateway.check_token.return_value = MicrosoftTokenInfo(
        expires_in=3599, app_name="Onyx"
    )
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(mailboxes=[mailbox()])
    gateway.resolve_mailbox.return_value = mailbox()
    gateway.probe_mailbox.return_value = folder()
    gateway.get_well_known_folder.return_value = folder(id="junk", display_name="Junk")
    gateway.list_child_folders.return_value = OutlookFolderPage(folders=[folder()])
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(changes=[])
    gateway.read_any_message.return_value = message()
    gateway.list_message_attachments.return_value = []
    return gateway


def check_context(
    gateway: MagicMock,
    connector_specific_config: dict[str, Any] | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.OUTLOOK,
        credential_json=CREDENTIALS,
        connector_specific_config=connector_specific_config,
        source_operations=gateway,
    )
