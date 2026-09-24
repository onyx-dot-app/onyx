from typing import NoReturn

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.graph_client import (
    is_permanent_refusal_status,
)

MISSING_CREDENTIAL_CODE = "missing_credential"
INVALID_AUTHORITY_CODE = "invalid_authority"


class OneDriveGraphError(Exception):
    def __init__(self, status: int | None, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(f"Graph {status} {code}: {message}")

    @property
    def is_permanent_refusal(self) -> bool:
        return is_permanent_refusal_status(self.status)

    @property
    def fails_the_attempt(self) -> bool:
        return self.status is None or self.status in (401, 429) or self.status >= 500


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
    if error.is_permanent_refusal:
        raise ConnectorValidationError(denied_message) from error
    if error.fails_the_attempt:
        raise UnexpectedValidationError(
            f"Graph is throttling or unavailable ({error.status} {error.code})."
        ) from error
    raise UnexpectedValidationError(f"Unexpected Graph error: {error}") from error
