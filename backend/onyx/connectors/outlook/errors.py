"""Map Outlook gateway failures onto the connector validation exceptions.

Shared by the capability checks and ``validate_connector_settings`` so both
paths tell an admin the same thing about the same failure.
"""

from typing import NoReturn

from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.microsoft_utils.graph_errors import (
    raise_for_graph_error as raise_for_microsoft_graph_error,
)


# Exchange caches app permission changes, so a freshly scoped mailbox can keep
# answering 403 for a while. Microsoft documents the window as 30 minutes to
# two hours.
def _scope_remediation(permission: str) -> str:
    return (
        f"Grant the `{permission}` application permission and admin-consent it, "
        "or, when the app is scoped with Exchange RBAC for Applications or an "
        "application access policy, add the mailbox to that scope. Exchange "
        "takes 30 minutes to two hours to apply the change."
    )


EXCHANGE_SCOPE_REMEDIATION = _scope_remediation("Mail.Read")
CALENDAR_READ_REMEDIATION = _scope_remediation("Calendars.Read")

MAILBOX_UNAVAILABLE_REMEDIATION = (
    "Use the user principal name or primary SMTP address of a licensed, "
    "enabled mailbox. Shared mailboxes are sign-in disabled and must be "
    "listed explicitly."
)

USER_LISTING_DENIED = (
    "The app cannot look up the tenant's users, which every-mailbox mode and "
    "address resolution both need. Grant the `User.Read.All` application "
    "permission and admin-consent it."
)


def raise_for_graph_error(
    error: MicrosoftGraphError,
    denied_message: str,
    remediation: str = EXCHANGE_SCOPE_REMEDIATION,
) -> NoReturn:
    raise_for_microsoft_graph_error(
        error,
        denied_message,
        remediation=remediation,
        permanent_refusal_message=(
            f"Graph found no usable mailbox ({error.code}). "
            f"{MAILBOX_UNAVAILABLE_REMEDIATION}"
        ),
    )
