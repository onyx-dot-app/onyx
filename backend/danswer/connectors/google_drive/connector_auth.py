import json
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import ParseResult
from urllib.parse import urlparse

from google.auth.transport.requests import Request  # type: ignore
from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from sqlalchemy.orm import Session

from danswer.configs.app_configs import ENTERPRISE_EDITION_ENABLED
from danswer.configs.app_configs import WEB_DOMAIN
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import KV_CRED_KEY
from danswer.configs.constants import KV_GOOGLE_DRIVE_CRED_KEY
from danswer.configs.constants import KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY
from danswer.connectors.google_drive.constants import BASE_SCOPES
from danswer.connectors.google_drive.constants import (
    DB_CREDENTIALS_DICT_DELEGATED_USER_KEY,
)
from danswer.connectors.google_drive.constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.connectors.google_drive.constants import DB_CREDENTIALS_DICT_TOKEN_KEY
from danswer.connectors.google_drive.constants import FETCH_GROUPS_SCOPES
from danswer.connectors.google_drive.constants import FETCH_PERMISSIONS_SCOPES
from danswer.db.credentials import update_credential_json
from danswer.db.models import User
from danswer.key_value_store.factory import get_kv_store
from danswer.server.documents.models import CredentialBase
from danswer.server.documents.models import GoogleAppCredentials
from danswer.server.documents.models import GoogleServiceAccountKey
from danswer.utils.logger import setup_logger

logger = setup_logger()


def build_gdrive_scopes() -> list[str]:
    base_scopes: list[str] = BASE_SCOPES
    permissions_scopes: list[str] = FETCH_PERMISSIONS_SCOPES
    groups_scopes: list[str] = FETCH_GROUPS_SCOPES

    if ENTERPRISE_EDITION_ENABLED:
        return base_scopes + permissions_scopes + groups_scopes
    return base_scopes + permissions_scopes


def _build_frontend_google_drive_redirect() -> str:
    return f"{WEB_DOMAIN}/admin/connectors/google-drive/auth/callback"


def get_google_drive_creds_for_authorized_user(
    token_json_str: str, scopes: list[str] = build_gdrive_scopes()
) -> OAuthCredentials | None:
    creds_json = json.loads(token_json_str)
    creds = OAuthCredentials.from_authorized_user_info(creds_json, scopes)
    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            if creds.valid:
                logger.notice("Refreshed Google Drive tokens.")
                return creds
        except Exception as e:
            logger.exception(f"Failed to refresh google drive access token due to: {e}")
            return None

    return None


def _get_google_drive_creds_for_service_account(
    service_account_key_json_str: str, scopes: list[str] = build_gdrive_scopes()
) -> ServiceAccountCredentials | None:
    service_account_key = json.loads(service_account_key_json_str)
    creds = ServiceAccountCredentials.from_service_account_info(
        service_account_key, scopes=scopes
    )
    if not creds.valid or not creds.expired:
        creds.refresh(Request())
    return creds if creds.valid else None


def get_google_drive_creds(
    credentials: dict[str, str], scopes: list[str] = build_gdrive_scopes()
) -> tuple[ServiceAccountCredentials | OAuthCredentials, dict[str, str] | None]:
    oauth_creds = None
    service_creds = None
    new_creds_dict = None
    if DB_CREDENTIALS_DICT_TOKEN_KEY in credentials:
        access_token_json_str = cast(str, credentials[DB_CREDENTIALS_DICT_TOKEN_KEY])
        oauth_creds = get_google_drive_creds_for_authorized_user(
            token_json_str=access_token_json_str, scopes=scopes
        )

        # tell caller to update token stored in DB if it has changed
        # (e.g. the token has been refreshed)
        new_creds_json_str = oauth_creds.to_json() if oauth_creds else ""
        if new_creds_json_str != access_token_json_str:
            new_creds_dict = {DB_CREDENTIALS_DICT_TOKEN_KEY: new_creds_json_str}

    elif DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY in credentials:
        service_account_key_json_str = credentials[
            DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
        ]
        service_creds = _get_google_drive_creds_for_service_account(
            service_account_key_json_str=service_account_key_json_str,
            scopes=scopes,
        )

        # "Impersonate" a user if one is specified
        delegated_user_email = cast(
            str | None, credentials.get(DB_CREDENTIALS_DICT_DELEGATED_USER_KEY)
        )
        if delegated_user_email:
            service_creds = (
                service_creds.with_subject(delegated_user_email)
                if service_creds
                else None
            )

    creds: ServiceAccountCredentials | OAuthCredentials | None = (
        oauth_creds or service_creds
    )
    if creds is None:
        raise PermissionError(
            "Unable to access Google Drive - unknown credential structure."
        )

    return creds, new_creds_dict


def verify_csrf(credential_id: int, state: str) -> None:
    csrf = get_kv_store().load(KV_CRED_KEY.format(str(credential_id)))
    if csrf != state:
        raise PermissionError(
            "State from Google Drive Connector callback does not match expected"
        )


def get_auth_url(credential_id: int) -> str:
    creds_str = str(get_kv_store().load(KV_GOOGLE_DRIVE_CRED_KEY))
    credential_json = json.loads(creds_str)
    flow = InstalledAppFlow.from_client_config(
        credential_json,
        scopes=build_gdrive_scopes(),
        redirect_uri=_build_frontend_google_drive_redirect(),
    )
    auth_url, _ = flow.authorization_url(prompt="consent")

    parsed_url = cast(ParseResult, urlparse(auth_url))
    params = parse_qs(parsed_url.query)

    get_kv_store().store(
        KV_CRED_KEY.format(credential_id), params.get("state", [None])[0], encrypt=True
    )  # type: ignore
    return str(auth_url)


def update_credential_access_tokens(
    auth_code: str,
    credential_id: int,
    user: User,
    db_session: Session,
) -> OAuthCredentials | None:
    app_credentials = get_google_app_cred()
    flow = InstalledAppFlow.from_client_config(
        app_credentials.model_dump(),
        scopes=build_gdrive_scopes(),
        redirect_uri=_build_frontend_google_drive_redirect(),
    )
    flow.fetch_token(code=auth_code)
    creds = flow.credentials
    token_json_str = creds.to_json()
    new_creds_dict = {DB_CREDENTIALS_DICT_TOKEN_KEY: token_json_str}

    if not update_credential_json(credential_id, new_creds_dict, user, db_session):
        return None
    return creds


def build_service_account_creds(
    source: DocumentSource,
    delegated_user_email: str | None = None,
) -> CredentialBase:
    service_account_key = get_service_account_key()

    credential_dict = {
        DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_key.json(),
    }
    if delegated_user_email:
        credential_dict[DB_CREDENTIALS_DICT_DELEGATED_USER_KEY] = delegated_user_email

    return CredentialBase(
        credential_json=credential_dict,
        admin_public=True,
        source=DocumentSource.GOOGLE_DRIVE,
    )


def get_google_app_cred() -> GoogleAppCredentials:
    creds_str = str(get_kv_store().load(KV_GOOGLE_DRIVE_CRED_KEY))
    return GoogleAppCredentials(**json.loads(creds_str))


def upsert_google_app_cred(app_credentials: GoogleAppCredentials) -> None:
    get_kv_store().store(KV_GOOGLE_DRIVE_CRED_KEY, app_credentials.json(), encrypt=True)


def delete_google_app_cred() -> None:
    get_kv_store().delete(KV_GOOGLE_DRIVE_CRED_KEY)


def get_service_account_key() -> GoogleServiceAccountKey:
    creds_str = str(get_kv_store().load(KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY))
    return GoogleServiceAccountKey(**json.loads(creds_str))


def upsert_service_account_key(service_account_key: GoogleServiceAccountKey) -> None:
    get_kv_store().store(
        KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY, service_account_key.json(), encrypt=True
    )


def delete_service_account_key() -> None:
    get_kv_store().delete(KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY)
