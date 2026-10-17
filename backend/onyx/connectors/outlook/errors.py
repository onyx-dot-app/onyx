"""Map Outlook gateway failures onto the connector validation exceptions.

Shared by the capability checks and ``validate_connector_settings`` so both
paths tell an admin the same thing about the same failure.
"""

from typing import NoReturn

from onyx.connectors.exceptions import InconclusiveValidationError
from onyx.connectors.microsoft_utils.check_text import MicrosoftRowText
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


GROUP_LISTING_DENIED = (
    "The app cannot read the tenant's groups, which choosing mailboxes by group needs."
)
GROUP_LISTING_REMEDIATION = (
    "Grant the `GroupMember.Read.All` application permission and admin-consent it."
)

GROUP_UNAVAILABLE_REMEDIATION = (
    "Use the display name or the object id of an Entra group. When several "
    "groups share the name, use the object id."
)


# The gateway's code when a lookup follows too many empty pages.
EMPTY_PAGES_CODE = "EmptyPages"


def raise_for_graph_error(
    error: MicrosoftGraphError,
    denied_message: str,
    remediation: str = EXCHANGE_SCOPE_REMEDIATION,
    *,
    denied_row: MicrosoftRowText | None = None,
    not_found_row: MicrosoftRowText | None = None,
    empty_pages_row: MicrosoftRowText | None = None,
    request: str = "the request",
) -> NoReturn:
    """``empty_pages_row`` is the row when Graph kept answering empty pages,
    which proves nothing about the grant."""
    if error.code == EMPTY_PAGES_CODE:
        row: MicrosoftRowText = empty_pages_row or MicrosoftRowText(
            summary="Mailbox lookup did not finish",
            description="Microsoft kept returning empty pages.\nRe-run the checks later.",
        )
        raise InconclusiveValidationError(
            str(error), summary=row.summary, description=row.description
        ) from error
    raise_for_microsoft_graph_error(
        error,
        denied_message,
        remediation=remediation,
        permanent_refusal_message=(
            f"Graph found no usable mailbox ({error.code}). "
            f"{MAILBOX_UNAVAILABLE_REMEDIATION}"
        ),
        denied_row=denied_row,
        not_found_row=not_found_row,
        request=request,
    )
