import json
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import ParseResult
from urllib.parse import urlparse

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
from sqlalchemy.orm import Session

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import KV_CRED_KEY
from onyx.configs.constants import KV_GMAIL_CRED_KEY
from onyx.configs.constants import KV_GMAIL_SERVICE_ACCOUNT_KEY
from onyx.configs.constants import KV_GOOGLE_DRIVE_CRED_KEY
from onyx.configs.constants import KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.resources import get_gmail_service
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import (
    GOOGLE_SCOPES,
)
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)
from onyx.connectors.google_utils.shared_constants import (
    MISSING_SCOPES_ERROR_STR,
)
from onyx.connectors.google_utils.shared_constants import (
    ONYX_SCOPE_INSTRUCTIONS,
)
from onyx.db.credentials import update_credential_json
from onyx.db.models import User
from onyx.key_value_store.factory import get_kv_store
from onyx.server.documents.models import CredentialBase
from onyx.server.documents.models import GoogleAppCredentials
from onyx.server.documents.models import GoogleServiceAccountKey
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _build_frontend_google_drive_redirect(source: DocumentSource) -> str:
    if source == DocumentSource.GOOGLE_DRIVE:
        return f"{WEB_DOMAIN}/admin/connectors/google-drive/auth/callback"
    elif source == DocumentSource.GMAIL:
        return f"{WEB_DOMAIN}/admin/connectors/gmail/auth/callback"
    else:
        raise ValueError(f"Unsupported source: {source}")


def _get_current_oauth_user(creds: OAuthCredentials, source: DocumentSource) -> str:
    if source == DocumentSource.GOOGLE_DRIVE:
        drive_service = get_drive_service(creds)
        user_info = (
            drive_service.about()
            .get(
                fields="user(emailAddress)",
            )
            .execute()
        )
        email = user_info.get("user", {}).get("emailAddress")
    elif source == DocumentSource.GMAIL:
        gmail_service = get_gmail_service(creds)
        user_info = (
            gmail_service.users()
            .getProfile(
                userId="me",
                fields="emailAddress",
            )
            .execute()
        )
        email = user_info.get("emailAddress")
    else:
        raise ValueError(f"Unsupported source: {source}")
    return email


def verify_csrf(credential_id: int, state: str) -> None:
    csrf = get_kv_store().load(KV_CRED_KEY.format(str(credential_id)))
    if csrf != state:
        raise PermissionError(
            "State from Google Drive Connector callback does not match expected"
        )


def update_credential_access_tokens(
    auth_code: str,
    credential_id: int,
    user: User,
    db_session: Session,
    source: DocumentSource,
    auth_method: GoogleOAuthAuthenticationMethod,
) -> OAuthCredentials | None:
    app_credentials = get_google_app_cred(source)
    flow = InstalledAppFlow.from_client_config(
        app_credentials.model_dump(),
        scopes=GOOGLE_SCOPES[source],
        redirect_uri=_build_frontend_google_drive_redirect(source),
    )
    flow.fetch_token(code=auth_code)
    creds = flow.credentials
    token_json_str = creds.to_json()

    # Get user email from Google API so we know who
    # the primary admin is for this connector
    try:
        email = _get_current_oauth_user(creds, source)
    except Exception as e:
        if MISSING_SCOPES_ERROR_STR in str(e):
            raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
        raise e

    new_creds_dict = {
        DB_CREDENTIALS_DICT_TOKEN_KEY: token_json_str,
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: email,
        DB_CREDENTIALS_AUTHENTICATION_METHOD: auth_method.value,
    }

    if not update_credential_json(credential_id, new_creds_dict, user, db_session):
        return None
    return creds


def build_service_account_creds(
    source: DocumentSource,
    primary_admin_email: str | None = None,
    name: str | None = None,
) -> CredentialBase:
    service_account_key = get_service_account_key(source=source)

    credential_dict = {
        DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_key.json(),
    }
    if primary_admin_email:
        credential_dict[DB_CREDENTIALS_PRIMARY_ADMIN_KEY] = primary_admin_email

    credential_dict[DB_CREDENTIALS_AUTHENTICATION_METHOD] = (
        GoogleOAuthAuthenticationMethod.UPLOADED.value
    )

    return CredentialBase(
        credential_json=credential_dict,
        admin_public=True,
        source=source,
        name=name,
    )


def get_auth_url(credential_id: int, source: DocumentSource) -> str:
    if source == DocumentSource.GOOGLE_DRIVE:
        creds_str = str(get_kv_store().load(KV_GOOGLE_DRIVE_CRED_KEY))
    elif source == DocumentSource.GMAIL:
        creds_str = str(get_kv_store().load(KV_GMAIL_CRED_KEY))
    else:
        raise ValueError(f"Unsupported source: {source}")
    credential_json = json.loads(creds_str)
    flow = InstalledAppFlow.from_client_config(
        credential_json,
        scopes=GOOGLE_SCOPES[source],
        redirect_uri=_build_frontend_google_drive_redirect(source),
    )
    auth_url, _ = flow.authorization_url(prompt="consent")

    parsed_url = cast(ParseResult, urlparse(auth_url))
    params = parse_qs(parsed_url.query)

    get_kv_store().store(
        KV_CRED_KEY.format(credential_id), params.get("state", [None])[0], encrypt=True
    )  # type: ignore
    return str(auth_url)


def get_google_app_cred(source: DocumentSource) -> GoogleAppCredentials:
    if source == DocumentSource.GOOGLE_DRIVE:
        creds_str = str(get_kv_store().load(KV_GOOGLE_DRIVE_CRED_KEY))
    elif source == DocumentSource.GMAIL:
        creds_str = str(get_kv_store().load(KV_GMAIL_CRED_KEY))
    else:
        raise ValueError(f"Unsupported source: {source}")
    return GoogleAppCredentials(**json.loads(creds_str))


def upsert_google_app_cred(
    app_credentials: GoogleAppCredentials, source: DocumentSource
) -> None:
    if source == DocumentSource.GOOGLE_DRIVE:
        get_kv_store().store(
            KV_GOOGLE_DRIVE_CRED_KEY, app_credentials.json(), encrypt=True
        )
    elif source == DocumentSource.GMAIL:
        get_kv_store().store(KV_GMAIL_CRED_KEY, app_credentials.json(), encrypt=True)
    else:
        raise ValueError(f"Unsupported source: {source}")


def delete_google_app_cred(source: DocumentSource) -> None:
    if source == DocumentSource.GOOGLE_DRIVE:
        get_kv_store().delete(KV_GOOGLE_DRIVE_CRED_KEY)
    elif source == DocumentSource.GMAIL:
        get_kv_store().delete(KV_GMAIL_CRED_KEY)
    else:
        raise ValueError(f"Unsupported source: {source}")


def get_service_account_key(source: DocumentSource) -> GoogleServiceAccountKey:
    if source == DocumentSource.GOOGLE_DRIVE:
        creds_str = str(get_kv_store().load(KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY))
    elif source == DocumentSource.GMAIL:
        creds_str = str(get_kv_store().load(KV_GMAIL_SERVICE_ACCOUNT_KEY))
    else:
        raise ValueError(f"Unsupported source: {source}")
    return GoogleServiceAccountKey(**json.loads(creds_str))


def upsert_service_account_key(
    service_account_key: GoogleServiceAccountKey, source: DocumentSource
) -> None:
    if source == DocumentSource.GOOGLE_DRIVE:
        get_kv_store().store(
            KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY,
            service_account_key.json(),
            encrypt=True,
        )
    elif source == DocumentSource.GMAIL:
        get_kv_store().store(
            KV_GMAIL_SERVICE_ACCOUNT_KEY, service_account_key.json(), encrypt=True
        )
    else:
        raise ValueError(f"Unsupported source: {source}")


def delete_service_account_key(source: DocumentSource) -> None:
    if source == DocumentSource.GOOGLE_DRIVE:
        get_kv_store().delete(KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY)
    elif source == DocumentSource.GMAIL:
        get_kv_store().delete(KV_GMAIL_SERVICE_ACCOUNT_KEY)
    else:
        raise ValueError(f"Unsupported source: {source}")
