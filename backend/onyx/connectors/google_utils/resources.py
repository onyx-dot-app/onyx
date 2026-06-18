from collections.abc import Callable

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.discovery import Resource

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


class ImpersonationError(Exception):
    """Raised when the service account cannot impersonate a user."""

    def __init__(self, user_email: str, original: RefreshError) -> None:
        super().__init__(f"Cannot impersonate '{user_email}'")
        self.user_email = user_email
        self.original = original


class UserRemovedError(ImpersonationError):
    """Raised when the impersonation failure is confirmed to be a deleted/suspended user."""


def make_user_removal_checker(
    user_email: str,
    get_fresh_emails: Callable[[], list[str]] | None = None,
) -> Callable[[], bool]:
    """Return a callable that checks whether user_email was removed from the workspace.

    The Admin SDK callback is fired at most once regardless of how many times
    the returned callable is invoked.
    """
    checked = False
    user_removed = False

    def is_user_removed() -> bool:
        nonlocal checked, user_removed
        if not checked:
            checked = True
            if get_fresh_emails is not None:
                try:
                    user_removed = user_email not in get_fresh_emails()
                except Exception:
                    pass
        return user_removed

    return is_user_removed


def _get_google_service(
    service_name: str,
    service_version: str,
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDriveService | GoogleDocsService | AdminService | GmailService:
    service: Resource
    if isinstance(creds, ServiceAccountCredentials):
        # NOTE: https://developers.google.com/identity/protocols/oauth2/service-account#error-codes
        creds = creds.with_subject(user_email)
        service = build(service_name, service_version, credentials=creds)
    elif isinstance(creds, OAuthCredentials):
        service = build(service_name, service_version, credentials=creds)

    return service


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
