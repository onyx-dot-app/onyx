from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from requests import Response
from requests.exceptions import HTTPError

from onyx.configs.app_configs import SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.salesforce.models import (
    SalesforceAuthenticationMethod,
    SalesforceAuthorizationCodeTokenRequest,
    SalesforceLegacyCredentials,
    SalesforceOAuthCredentials,
    SalesforceRefreshTokenRequest,
    SalesforceSessionCredentials,
    SalesforceTokenResponse,
    parse_salesforce_credentials,
    validate_salesforce_my_domain_url,
)
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce
from onyx.utils.redaction import scrub_sensitive_values
from onyx.utils.retry_wrapper import request_with_retries

_SALESFORCE_TOKEN_PATH = "/services/oauth2/token"
_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
_CONTENT_TYPE_HEADER = "Content-Type"
_POST_METHOD = "POST"
_MAX_OAUTH_ERROR_LENGTH = 500


class SalesforceOAuthTokenError(RuntimeError):
    pass


def _get_salesforce_oauth_config() -> tuple[str, str]:
    if not SALESFORCE_CLIENT_ID or not SALESFORCE_CLIENT_SECRET:
        raise ValueError(
            "SALESFORCE_CLIENT_ID and SALESFORCE_CLIENT_SECRET must be set"
        )
    return SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET


def _sensitive_request_values(
    token_request: (
        SalesforceAuthorizationCodeTokenRequest | SalesforceRefreshTokenRequest
    ),
) -> list[str]:
    values = [token_request.client_secret]
    if isinstance(token_request, SalesforceAuthorizationCodeTokenRequest):
        values.extend([token_request.code, token_request.code_verifier])
    else:
        values.append(token_request.refresh_token)
    return values


def _safe_oauth_error_text(value: Any, sensitive_values: list[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(scrub_sensitive_values(value, sensitive_values).split())
    return normalized[:_MAX_OAUTH_ERROR_LENGTH] or None


def _salesforce_token_error(
    response: Response,
    token_request: (
        SalesforceAuthorizationCodeTokenRequest | SalesforceRefreshTokenRequest
    ),
) -> SalesforceOAuthTokenError:
    message = f"Salesforce token request failed with status {response.status_code}"
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return SalesforceOAuthTokenError(message)
    if not isinstance(payload, dict):
        return SalesforceOAuthTokenError(message)

    sensitive_values = _sensitive_request_values(token_request)
    error = _safe_oauth_error_text(payload.get("error"), sensitive_values)
    description = _safe_oauth_error_text(
        payload.get("error_description"), sensitive_values
    )
    details = ": ".join(detail for detail in (error, description) if detail)
    return SalesforceOAuthTokenError(f"{message}: {details}" if details else message)


def _request_salesforce_token(
    login_url: str,
    token_request: (
        SalesforceAuthorizationCodeTokenRequest | SalesforceRefreshTokenRequest
    ),
) -> SalesforceTokenResponse:
    validated_login_url = validate_salesforce_my_domain_url(login_url)
    try:
        response = request_with_retries(
            method=_POST_METHOD,
            url=f"{validated_login_url}{_SALESFORCE_TOKEN_PATH}",
            data=token_request.model_dump(mode="json"),
            headers={_CONTENT_TYPE_HEADER: _FORM_CONTENT_TYPE},
            log_request_data=False,
            tries=1,
        )
    except HTTPError as error:
        if error.response is None:
            raise SalesforceOAuthTokenError("Salesforce token request failed") from None
        response = error.response
    if not response.ok:
        raise _salesforce_token_error(response, token_request)
    return SalesforceTokenResponse.model_validate(response.json())


def exchange_salesforce_authorization_code(
    login_url: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> SalesforceOAuthCredentials:
    client_id, client_secret = _get_salesforce_oauth_config()
    token_response = _request_salesforce_token(
        login_url,
        SalesforceAuthorizationCodeTokenRequest(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        ),
    )
    if not token_response.refresh_token:
        raise ValueError(
            "Salesforce authorization response did not include a refresh token"
        )

    return SalesforceOAuthCredentials(
        authentication_method=SalesforceAuthenticationMethod.OAUTH,
        sf_access_token=token_response.access_token,
        sf_refresh_token=token_response.refresh_token,
        sf_instance_url=token_response.instance_url,
        sf_login_url=login_url,
    )


def refresh_salesforce_oauth_credentials(
    credentials: SalesforceOAuthCredentials,
) -> SalesforceOAuthCredentials:
    client_id, client_secret = _get_salesforce_oauth_config()
    token_response = _request_salesforce_token(
        credentials.sf_login_url,
        SalesforceRefreshTokenRequest(
            refresh_token=credentials.sf_refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        ),
    )
    return SalesforceOAuthCredentials(
        authentication_method=credentials.authentication_method,
        sf_access_token=token_response.access_token,
        sf_refresh_token=token_response.refresh_token or credentials.sf_refresh_token,
        sf_instance_url=token_response.instance_url,
        sf_login_url=credentials.sf_login_url,
    )


def _session_credentials(
    credentials: SalesforceOAuthCredentials,
) -> SalesforceSessionCredentials:
    instance_host = urlsplit(credentials.sf_instance_url).hostname
    if instance_host is None:
        raise ValueError("Salesforce instance URL has no host")
    return SalesforceSessionCredentials(
        sf_access_token=credentials.sf_access_token,
        sf_instance_host=instance_host,
    )


def _build_refresh_callback(
    credentials_provider: CredentialsProviderInterface,
) -> Callable[[str], SalesforceSessionCredentials]:
    def refresh(expired_access_token: str) -> SalesforceSessionCredentials:
        with credentials_provider:
            current = parse_salesforce_credentials(
                credentials_provider.get_credentials()
            )
            if not isinstance(current, SalesforceOAuthCredentials):
                raise ValueError("Salesforce OAuth credentials are no longer available")

            if current.sf_access_token == expired_access_token:
                current = refresh_salesforce_oauth_credentials(current)
                credentials_provider.set_credentials(current.model_dump(mode="json"))
            return _session_credentials(current)

    return refresh


def build_salesforce_client(
    credentials_provider: CredentialsProviderInterface,
) -> OnyxSalesforce:
    credentials = parse_salesforce_credentials(credentials_provider.get_credentials())
    if isinstance(credentials, SalesforceLegacyCredentials):
        return OnyxSalesforce(
            username=credentials.sf_username,
            password=credentials.sf_password,
            security_token=credentials.sf_security_token,
            domain="test" if credentials.is_sandbox else None,
        )

    return OnyxSalesforce(
        session_id=credentials.sf_access_token,
        instance_url=credentials.sf_instance_url,
        refresh_callback=_build_refresh_callback(credentials_provider),
    )
