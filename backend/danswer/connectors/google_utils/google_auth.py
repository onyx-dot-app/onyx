import json
from typing import cast

from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore

from danswer.configs.constants import DocumentSource
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from danswer.connectors.google_utils.shared_constants import (
    GOOGLE_SCOPES,
)
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_google_oauth_creds(
    token_json_str: str, source: DocumentSource
) -> OAuthCredentials | None:
    creds_json = json.loads(token_json_str)
    creds = OAuthCredentials.from_authorized_user_info(
        info=creds_json,
        scopes=GOOGLE_SCOPES[source],
    )
    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            if creds.valid:
                logger.notice("Refreshed Google Drive tokens.")
                return creds
        except Exception:
            logger.exception("Failed to refresh google drive access token due to:")
            return None

    return None


def get_google_creds(
    credentials: dict[str, str],
    source: DocumentSource,
) -> tuple[ServiceAccountCredentials | OAuthCredentials, dict[str, str] | None]:
    """Checks for two different types of credentials.
    (1) A credential which holds a token acquired via a user going thorough
    the Google OAuth flow.
    (2) A credential which holds a service account key JSON file, which
    can then be used to impersonate any user in the workspace.
    """
    oauth_creds = None
    service_creds = None
    new_creds_dict = None
    if DB_CREDENTIALS_DICT_TOKEN_KEY in credentials:
        # OAUTH
        access_token_json_str = cast(str, credentials[DB_CREDENTIALS_DICT_TOKEN_KEY])
        oauth_creds = get_google_oauth_creds(
            token_json_str=access_token_json_str, source=source
        )

        # tell caller to update token stored in DB if it has changed
        # (e.g. the token has been refreshed)
        new_creds_json_str = oauth_creds.to_json() if oauth_creds else ""
        if new_creds_json_str != access_token_json_str:
            new_creds_dict = {
                DB_CREDENTIALS_DICT_TOKEN_KEY: new_creds_json_str,
                DB_CREDENTIALS_PRIMARY_ADMIN_KEY: credentials[
                    DB_CREDENTIALS_PRIMARY_ADMIN_KEY
                ],
            }
    elif DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY in credentials:
        # SERVICE ACCOUNT
        service_account_key_json_str = credentials[
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
        ]
        service_account_key = json.loads(service_account_key_json_str)

        service_creds = ServiceAccountCredentials.from_service_account_info(
            service_account_key, scopes=GOOGLE_SCOPES[source]
        )

        if not service_creds.valid or not service_creds.expired:
            service_creds.refresh(Request())

        if not service_creds.valid:
            raise PermissionError(
                f"Unable to access {source} - service account credentials are invalid."
            )

    creds: ServiceAccountCredentials | OAuthCredentials | None = (
        oauth_creds or service_creds
    )
    if creds is None:
        raise PermissionError(
            f"Unable to access {source} - unknown credential structure."
        )

    return creds, new_creds_dict
