"""Map Outlook gateway failures onto the connector validation exceptions.

Shared by the capability checks and ``validate_connector_settings`` so both
paths tell an admin the same thing about the same failure.
"""

from typing import NoReturn

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.outlook.models import (
    INVALID_AUTH_METHOD_CODE,
    INVALID_AUTHORITY_CODE,
    INVALID_CERTIFICATE_CODE,
    MISSING_CREDENTIAL_CODE,
    OutlookAuthError,
    OutlookGraphError,
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


# OAuth error codes the token endpoint returns for its own trouble, never for
# a bad credential (RFC 6749 section 5.2).
_TRANSIENT_OAUTH_CODES = frozenset({"temporarily_unavailable", "server_error"})


def raise_for_auth_error(error: OutlookAuthError) -> NoReturn:
    """Token refusals are about the credential unless the endpoint says otherwise."""
    if error.code in _TRANSIENT_OAUTH_CODES:
        raise UnexpectedValidationError(
            f"Microsoft's token endpoint is unavailable ({error}). Re-run the "
            "checks in a few minutes."
        ) from error
    if error.code == MISSING_CREDENTIAL_CODE:
        raise CredentialInvalidError(
            f"Outlook credential is incomplete: {error}"
        ) from error
    if error.code == INVALID_AUTHORITY_CODE:
        raise CredentialInvalidError(
            "Microsoft does not know this directory. Check the directory "
            f"(tenant) id and the authority host ({error})."
        ) from error
    if error.code == INVALID_CERTIFICATE_CODE:
        raise CredentialInvalidError(
            "The PFX bundle could not be opened. Check the file and its "
            "certificate password."
        ) from error
    if error.code == INVALID_AUTH_METHOD_CODE:
        raise CredentialInvalidError(str(error)) from error
    if error.code == "invalid_client":
        raise CredentialInvalidError(
            "Microsoft rejected the client secret or certificate. It is wrong, "
            "expired, or belongs to a different app registration."
        ) from error
    if error.code in ("unauthorized_client", "invalid_request"):
        raise CredentialInvalidError(
            "Microsoft rejected the app registration. Check the client id and "
            f"directory id ({error.code})."
        ) from error
    raise CredentialInvalidError(f"Microsoft did not issue a token: {error}") from error


def raise_for_graph_error(
    error: OutlookGraphError,
    denied_message: str,
    remediation: str = EXCHANGE_SCOPE_REMEDIATION,
) -> NoReturn:
    """Turn a Graph HTTP failure into the validation family.

    ``denied_message`` explains what a 403 means for the call that failed, since
    a denied mailbox and a missing permission look identical on the wire, and
    ``remediation`` names the grant that call needs.
    """
    if error.status == 401:
        raise CredentialExpiredError(
            f"Graph rejected the access token ({error.code})."
        ) from error
    if error.status == 403:
        raise InsufficientPermissionsError(
            f"{denied_message} Graph reported `{error.code}`. {remediation}"
        ) from error
    if error.status == 404:
        raise ConnectorValidationError(
            f"Graph found no mailbox ({error.code}). {MAILBOX_UNAVAILABLE_REMEDIATION}"
        ) from error
    if error.fails_the_attempt:
        raise UnexpectedValidationError(
            f"Graph is throttling or unreachable ({error.status} {error.code}). "
            "Re-run the checks in a few minutes."
        ) from error
    raise UnexpectedValidationError(f"Unexpected Graph error: {error}") from error
