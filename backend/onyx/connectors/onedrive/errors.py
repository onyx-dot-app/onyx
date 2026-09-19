from typing import NoReturn

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)

MISSING_CREDENTIAL_CODE = "missing_credential"
INVALID_AUTHORITY_CODE = "invalid_authority"


class OneDriveGraphError(Exception):
    def __init__(self, status: int | None, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Graph {status} {code}: {message}")


class OneDriveAuthError(Exception):
    def __init__(self, code: str, description: str) -> None:
        self.code = code
        super().__init__(f"{code}: {description}")


def raise_for_auth_error(error: OneDriveAuthError) -> NoReturn:
    if error.code in {"temporarily_unavailable", "server_error"}:
        raise UnexpectedValidationError(
            f"Microsoft's token endpoint is unavailable ({error})."
        ) from error
    if error.code in {MISSING_CREDENTIAL_CODE, INVALID_AUTHORITY_CODE}:
        raise CredentialInvalidError(
            "OneDrive credential is invalid; check all required fields."
        ) from error
    if error.code == "invalid_client":
        raise CredentialInvalidError(
            "Microsoft rejected the OneDrive client credential."
        ) from error
    raise CredentialInvalidError(f"Microsoft did not issue a token: {error}") from error


def raise_for_graph_error(error: OneDriveGraphError, denied_message: str) -> NoReturn:
    if error.status == 401:
        raise CredentialExpiredError("Graph rejected the access token.") from error
    if error.status == 403:
        raise InsufficientPermissionsError(denied_message) from error
    if error.status == 404:
        raise ConnectorValidationError(denied_message) from error
    if error.status is None or error.status == 429 or error.status >= 500:
        raise UnexpectedValidationError(
            f"Graph is throttling or unavailable ({error.status} {error.code})."
        ) from error
    raise UnexpectedValidationError(f"Unexpected Graph error: {error}") from error
