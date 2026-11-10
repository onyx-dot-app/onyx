import json
from enum import Enum
from functools import cache
from typing import Literal, overload

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import Resource, build, build_from_document
from googleapiclient.discovery_cache import get_static_doc

from onyx.configs.app_configs import GOOGLE_API_ENDPOINT_OVERRIDE
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


class GoogleService(Enum):
    DOCS = ("docs", "v1")
    DRIVE = ("drive", "v3")
    ADMIN = ("admin", "directory_v1")
    GMAIL = ("gmail", "v1")


@overload
def get_google_service(
    service: Literal[GoogleService.DOCS],
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDocsService: ...


@overload
def get_google_service(
    service: Literal[GoogleService.DRIVE],
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDriveService: ...


@overload
def get_google_service(
    service: Literal[GoogleService.ADMIN],
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> AdminService: ...


@overload
def get_google_service(
    service: Literal[GoogleService.GMAIL],
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GmailService: ...


def get_google_service(
    service: GoogleService,
    creds: ServiceAccountCredentials | OAuthCredentials,
    user_email: str | None = None,
) -> GoogleDriveService | GoogleDocsService | AdminService | GmailService:
    return build_google_service(service, get_impersonated_creds(creds, user_email))


def build_google_service(
    service: GoogleService, creds: ServiceAccountCredentials | OAuthCredentials
) -> GoogleDriveService | GoogleDocsService | AdminService | GmailService:
    """A client that uses `creds` as given: impersonate before calling this."""
    service_name, service_version = service.value
    resource: Resource
    if GOOGLE_API_ENDPOINT_OVERRIDE is None:
        resource = build(service_name, service_version, credentials=creds)
    else:
        resource = build_from_document(
            _overridden_discovery_doc(service_name, service_version),
            credentials=creds,
        )
    return resource


@cache
def _overridden_discovery_doc(service_name: str, service_version: str) -> str:
    """The bundled discovery document with its root URL set to
    GOOGLE_API_ENDPOINT_OVERRIDE. Batch requests read the root URL from the
    document, so `client_options.api_endpoint` would not redirect them."""
    raw = get_static_doc(service_name, service_version)
    if raw is None:
        raise ValueError(f"No bundled discovery document for {service_name}")
    doc = json.loads(raw)
    doc["rootUrl"] = GOOGLE_API_ENDPOINT_OVERRIDE
    doc["mtlsRootUrl"] = GOOGLE_API_ENDPOINT_OVERRIDE
    return json.dumps(doc)


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
