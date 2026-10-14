from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import Resource, build

from onyx.utils.logger import setup_logger

logger = setup_logger()


class GoogleDriveService(Resource):
    pass


class GoogleDocsService(Resource):
    pass


class AdminService(Resource):
    pass


class GmailService(Resource):
    pass


def _get_google_service(
    service_name: str,
    service_version: str,
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDriveService | GoogleDocsService | AdminService | GmailService:
    creds = get_impersonated_creds(creds, user_email)
    service: Resource = build(service_name, service_version, credentials=creds)
    return service  # ty: ignore[invalid-return-type]


def get_impersonated_creds(
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> ServiceAccountCredentials | OAuthCredentials:
    """Service-account creds impersonating `user_email` (domain-wide delegation);
    OAuth creds are returned unchanged."""
    if isinstance(creds, ServiceAccountCredentials):
        # https://developers.google.com/identity/protocols/oauth2/service-account#error-codes
        return creds.with_subject(user_email)
    return creds


def get_google_authorized_session(
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> AuthorizedSession:
    """Raw authorized HTTP session for Google REST endpoints the typed service
    builders don't cover (e.g. streaming a response under a byte cap). Caller owns
    the session and must close it."""
    return AuthorizedSession(get_impersonated_creds(creds, user_email))


def get_google_docs_service(
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDocsService:
    return _get_google_service(  # ty: ignore[invalid-return-type]
        "docs", "v1", creds, user_email
    )


def get_drive_service(
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDriveService:
    return _get_google_service(  # ty: ignore[invalid-return-type]
        "drive", "v3", creds, user_email
    )


def get_admin_service(
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> AdminService:
    return _get_google_service(  # ty: ignore[invalid-return-type]
        "admin", "directory_v1", creds, user_email
    )


def get_gmail_service(
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GmailService:
    return _get_google_service(  # ty: ignore[invalid-return-type]
        "gmail", "v1", creds, user_email
    )
