"""The row text and states every Microsoft connector's checks share: the
sign-in row, the throttled and unreachable rows, Error Details from a Graph
refusal, the certificate's end date and the app's name from the token, and
the checks after a failed sign-in, which do not run."""

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
    check_error_detail,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    UnexpectedValidationError,
    UnreachableValidationError,
    ValidationError,
)
from onyx.connectors.microsoft_utils import check_text
from onyx.connectors.microsoft_utils.check_text import (
    MicrosoftAccountLabels,
    MicrosoftRowText,
    sign_in_text,
)
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    MicrosoftAuthMethod,
    certificate_not_after,
    token_info,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    INVALID_AUTH_METHOD_CODE,
    INVALID_AUTHORITY_CODE,
    INVALID_CERTIFICATE_CODE,
    MISSING_CREDENTIAL_CODE,
    MicrosoftAuthError,
    MicrosoftGraphError,
    microsoft_error_from_exception,
    raise_for_auth_error,
    raise_for_graph_error,
    raise_for_sign_in_error,
)
from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo
from onyx.connectors.onedrive.capability_checks import build_onedrive_indexing_checks
from onyx.connectors.onedrive.source_operations import OneDriveSourceOperations
from onyx.connectors.outlook.capability_checks import build_outlook_indexing_checks
from onyx.connectors.outlook.source_operations import OutlookSourceOperations
from onyx.connectors.sharepoint.capability_checks import (
    build_sharepoint_indexing_checks,
)
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations

_LABELS = MicrosoftAccountLabels.with_prefix("SharePoint")
_GRAPH_URL = "https://graph.microsoft.com/v1.0/sites?search=*"


def _raised(raise_it: Any, *args: Any, **kwargs: Any) -> ValidationError:
    with pytest.raises(ValidationError) as raised:
        raise_it(*args, **kwargs)
    return raised.value


def _transport_error() -> MicrosoftGraphError:
    try:
        raise microsoft_error_from_exception(
            requests.ConnectionError("refused")
        ) from requests.ConnectionError("refused")
    except MicrosoftGraphError as error:
        return error


# --- Every row line fits the card ---


def test_every_shared_line_is_short_enough() -> None:
    rows: list[MicrosoftRowText] = [
        value
        for value in vars(check_text).values()
        if isinstance(value, MicrosoftRowText)
    ] + [
        check_text.missing_field_row(_LABELS, certificate=True),
        check_text.certificate_unreadable_row(_LABELS),
        check_text.credential_rejected_row(_LABELS, certificate=False),
        check_text.no_token_row("x"),
        check_text.unexpected_answer_row("the site listing"),
    ]

    for row in rows:
        assert len(row.summary) <= 40, row.summary
        assert len(row.description.splitlines()) <= 3, row.description


@pytest.mark.parametrize(
    ("token", "full_value"),
    [
        (
            MicrosoftTokenInfo(app_id="00000000-0000-0000-0000-000000000000"),
            "App ID: 00000000-0000-0000-0000-000000000000",
        ),
        (
            MicrosoftTokenInfo(
                app_name="Contoso Enterprise Search Indexer Production",
                certificate_not_after=datetime.now(timezone.utc) + timedelta(days=200),
            ),
            "App: Contoso Enterprise Search Indexer Production",
        ),
    ],
)
def test_a_long_app_name_or_id_fits_the_sign_in_line(
    token: MicrosoftTokenInfo, full_value: str
) -> None:
    sign_in = sign_in_text(token, _LABELS)

    assert len(sign_in.summary) <= 40, sign_in.summary
    assert sign_in.description is not None
    assert sign_in.description.splitlines()[0] == full_value
    assert len(sign_in.description.splitlines()) <= 3


# --- Sign-in refusals ---


def test_a_missing_field_names_the_fields_of_the_sign_in_method() -> None:
    secret = _raised(
        raise_for_auth_error, MicrosoftAuthError(MISSING_CREDENTIAL_CODE, ""), _LABELS
    )
    certificate = _raised(
        raise_for_auth_error,
        MicrosoftAuthError(MISSING_CREDENTIAL_CODE, "", certificate=True),
        _LABELS,
    )

    assert isinstance(secret, CredentialInvalidError)
    assert secret.summary == "A required account field is empty"
    assert secret.description is not None
    assert secret.description.endswith(
        "SharePoint Client ID, SharePoint Directory ID and SharePoint Client Secret."
    )
    assert certificate.description is not None
    assert "SharePoint Private Key" in certificate.description


@pytest.mark.parametrize(
    ("code", "summary"),
    [
        (INVALID_AUTH_METHOD_CODE, "Unknown sign-in method on the account"),
        (INVALID_CERTIFICATE_CODE, "Certificate file does not open"),
        (INVALID_AUTHORITY_CODE, "Directory ID not found"),
        ("invalid_client", "Secret or certificate was rejected"),
        ("unauthorized_client", "App registration not found"),
        ("access_denied", "Microsoft did not issue a token"),
        ("temporarily_unavailable", "Microsoft sign-in is unavailable"),
    ],
)
def test_each_sign_in_refusal_has_its_line(code: str, summary: str) -> None:
    error = _raised(raise_for_auth_error, MicrosoftAuthError(code, "x"), _LABELS)

    assert error.summary == summary


def test_an_expired_secret_says_so() -> None:
    error = _raised(
        raise_for_auth_error,
        MicrosoftAuthError("invalid_client", "AADSTS7000222: The secret expired."),
        _LABELS,
    )

    assert error.description is not None
    assert error.description.startswith("The client secret on this account has")
    assert "SharePoint Client Secret" in error.description


def test_an_expired_certificate_names_its_end_date() -> None:
    error = _raised(
        raise_for_auth_error,
        MicrosoftAuthError(
            "invalid_client",
            "AADSTS700027",
            certificate=True,
            certificate_not_after=datetime(2026, 1, 31, tzinfo=timezone.utc),
        ),
        _LABELS,
    )

    assert error.description is not None
    assert error.description.startswith(
        "The certificate on this account expired on 2026/01/31."
    )


@pytest.mark.parametrize(
    ("error", "error_class", "summary"),
    [
        (
            MicrosoftGraphError(429, "tooManyRequests", "slow down"),
            RateLimitedValidationError,
            "Microsoft is throttling requests",
        ),
        (
            _transport_error(),
            UnreachableValidationError,
            "Cannot reach Microsoft sign-in",
        ),
        (
            MicrosoftGraphError(503, "serviceUnavailable", "down"),
            UnexpectedValidationError,
            "Microsoft sign-in is unavailable",
        ),
        (
            MicrosoftGraphError(400, "invalid_request", "AADSTS900023"),
            CredentialInvalidError,
            "Microsoft refused the sign-in request",
        ),
        (
            MicrosoftGraphError(None, "JSONDecodeError", "not json"),
            UnexpectedValidationError,
            "Unexpected answer from Microsoft sign-in",
        ),
    ],
)
def test_a_token_request_without_an_oauth_error_maps_by_status(
    error: MicrosoftGraphError, error_class: type[ValidationError], summary: str
) -> None:
    raised = _raised(raise_for_sign_in_error, error)

    assert type(raised) is error_class
    assert raised.summary == summary


# --- Graph refusals after sign-in ---


def test_a_throttled_graph_call_stops_the_run() -> None:
    raised = _raised(
        raise_for_graph_error,
        MicrosoftGraphError(429, "tooManyRequests", "slow down"),
        "denied",
    )

    assert isinstance(raised, RateLimitedValidationError)
    assert raised.summary == "Microsoft is throttling requests"


def test_a_dropped_connection_is_unreachable() -> None:
    raised = _raised(raise_for_graph_error, _transport_error(), "denied")

    assert isinstance(raised, UnreachableValidationError)
    assert raised.summary == "Cannot reach Microsoft"


def test_a_rejected_token_is_rejected() -> None:
    raised = _raised(
        raise_for_graph_error,
        MicrosoftGraphError(401, "InvalidAuthenticationToken", ""),
        "x",
    )

    assert isinstance(raised, CredentialExpiredError)
    assert raised.summary == "Microsoft rejected the app's token"


def test_a_denial_takes_the_caller_row() -> None:
    row = MicrosoftRowText(summary="No permission to list sites", description="d")

    raised = _raised(
        raise_for_graph_error,
        MicrosoftGraphError(403, "accessDenied", "no"),
        "The app cannot list sites.",
        denied_row=row,
    )

    assert isinstance(raised, InsufficientPermissionsError)
    assert raised.summary == row.summary
    assert "accessDenied" in raised.message


def test_a_server_error_names_the_request() -> None:
    raised = _raised(
        raise_for_graph_error,
        MicrosoftGraphError(502, "badGateway", ""),
        "x",
        request="the site listing",
    )

    assert raised.summary == "Unexpected answer from Microsoft"
    assert raised.description is not None
    assert "the site listing" in raised.description


# --- Error Details ---


def test_a_graph_refusal_carries_the_request_and_body() -> None:
    response = requests.Response()
    response.status_code = 403
    response.url = _GRAPH_URL
    response._content = b'{"error": {"code": "accessDenied", "message": "no"}}'
    response.request = requests.Request("GET", _GRAPH_URL).prepare()

    error = microsoft_error_from_exception(requests.HTTPError(response=response))

    assert isinstance(error, SourceApiError)
    assert error.status == 403
    assert error.code == "accessDenied"
    detail = check_error_detail(error, CheckErrorKind.PERMISSION, [])
    assert detail is not None
    assert detail.request == "GET graph.microsoft.com/v1.0/sites"
    assert detail.response_excerpt is not None
    assert "accessDenied" in detail.response_excerpt


# --- The certificate's end date and the app's name ---


def _pfx(not_after: datetime) -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "onyx")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(not_after - timedelta(days=365))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"onyx", key, certificate, None, BestAvailableEncryption(b"secret")
    )


def test_the_certificate_end_date_reads_from_the_pfx() -> None:
    end = datetime(2027, 3, 1, tzinfo=timezone.utc)

    assert certificate_not_after(_pfx(end), "secret") == end
    assert certificate_not_after(_pfx(end), "wrong") is None
    assert certificate_not_after(b"not a pfx", "secret") is None


def _jwt(claims: dict[str, str]) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


@pytest.mark.parametrize(
    ("access_token", "summary"),
    [
        (
            _jwt({"app_displayname": "Onyx Indexer", "appid": "a1"}),
            "Signed in as Onyx Indexer",
        ),
        (_jwt({"appid": "a1"}), "Signed in as app a1"),
        ("opaque-token", "Signed in to Microsoft"),
    ],
)
def test_sign_in_names_the_app_from_the_token(access_token: str, summary: str) -> None:
    context = MicrosoftAuthContext(
        app=MagicMock(), method=MicrosoftAuthMethod.CLIENT_SECRET
    )

    info = token_info(context, {"access_token": access_token, "expires_in": 3599})

    assert info.expires_in == 3599
    assert sign_in_text(info, _LABELS).summary == summary


def test_a_certificate_near_its_end_date_gets_a_caveat() -> None:
    soon = datetime.now(timezone.utc) + timedelta(days=10)
    later = datetime.now(timezone.utc) + timedelta(days=200)

    near = sign_in_text(MicrosoftTokenInfo(certificate_not_after=soon), _LABELS)
    far = sign_in_text(MicrosoftTokenInfo(certificate_not_after=later), _LABELS)

    assert near.caveats and "SharePoint Private Key" in near.caveats[0]
    assert far.caveats == []
    assert far.description is not None
    assert far.description.startswith("Certificate valid until ")


# --- The checks after sign-in ---


class _Connector:
    def __init__(
        self,
        source: DocumentSource,
        gateway_class: type,
        checks: list[CapabilityCheck],
        sign_in_id: str,
        config: dict[str, Any],
    ) -> None:
        self.source = source
        self.gateway_class = gateway_class
        self.checks = checks
        self.sign_in_id = sign_in_id
        self.config = config


_CONNECTORS = [
    _Connector(
        DocumentSource.SHAREPOINT,
        SharepointSourceOperations,
        build_sharepoint_indexing_checks(),
        "sharepoint_token_auth",
        {"sites": ["https://contoso.sharepoint.com/sites/eng"]},
    ),
    _Connector(
        DocumentSource.ONEDRIVE,
        OneDriveSourceOperations,
        build_onedrive_indexing_checks(),
        "onedrive_token_auth",
        {},
    ),
    _Connector(
        DocumentSource.OUTLOOK,
        OutlookSourceOperations,
        build_outlook_indexing_checks(),
        "outlook_token_auth",
        {},
    ),
]


def _run(
    connector: _Connector, gateway: MagicMock, *, form_run: bool = False
) -> dict[str, CapabilityCheckResult]:
    context = CapabilityCheckContext(
        source=connector.source,
        credential_json={},
        connector_specific_config=connector.config,
        source_operations=gateway,
    )
    return {
        result.check_id: result
        for result in run_capability_checks(
            connector.checks, context, form_run=form_run
        )
    }


@pytest.mark.parametrize("connector", _CONNECTORS, ids=lambda c: c.source.value)
def test_a_failed_sign_in_is_one_row(connector: _Connector) -> None:
    gateway: MagicMock = create_autospec(connector.gateway_class, instance=True)
    gateway.check_token.side_effect = MicrosoftAuthError("invalid_client", "")

    results = _run(connector, gateway)

    sign_in = results.pop(connector.sign_in_id)
    assert sign_in.display_name == "Sign in to Microsoft"
    assert sign_in.status == CapabilityCheckStatus.FAILED
    assert sign_in.summary == "Secret or certificate was rejected"
    for result in results.values():
        # A settings check makes no call, so it runs.
        if not result.applicable or result.status == CapabilityCheckStatus.PASSED:
            continue
        assert result.status == CapabilityCheckStatus.SKIPPED, result.check_id
        assert result.blocked_by == connector.sign_in_id


@pytest.mark.parametrize("connector", _CONNECTORS, ids=lambda c: c.source.value)
def test_an_unreachable_sign_in_fails_only_a_form_run(connector: _Connector) -> None:
    gateway: MagicMock = create_autospec(connector.gateway_class, instance=True)
    gateway.check_token.side_effect = _transport_error()

    form = _run(connector, gateway, form_run=True)[connector.sign_in_id]
    stored = _run(connector, gateway)[connector.sign_in_id]

    assert form.status == CapabilityCheckStatus.FAILED
    assert stored.status == CapabilityCheckStatus.INCOMPLETE
    assert form.summary == stored.summary == "Cannot reach Microsoft sign-in"


@pytest.mark.parametrize("connector", _CONNECTORS, ids=lambda c: c.source.value)
def test_a_throttled_sign_in_stops_the_run(connector: _Connector) -> None:
    gateway: MagicMock = create_autospec(connector.gateway_class, instance=True)
    gateway.check_token.side_effect = MicrosoftGraphError(429, "tooManyRequests", "")

    results = _run(connector, gateway)

    sign_in = results.pop(connector.sign_in_id)
    assert sign_in.status == CapabilityCheckStatus.INCOMPLETE
    assert sign_in.error_kind == CheckErrorKind.RATE_LIMITED
    assert sign_in.summary == "Microsoft is throttling requests"
    for result in results.values():
        if result.applicable and result.status != CapabilityCheckStatus.PASSED:
            assert result.not_run_reason in (
                CheckNotRunReason.DEPENDENCY_INCOMPLETE,
                CheckNotRunReason.RATE_LIMITED,
            ), result.check_id


@pytest.mark.parametrize("connector", _CONNECTORS, ids=lambda c: c.source.value)
def test_sign_in_names_the_app(connector: _Connector) -> None:
    gateway: MagicMock = create_autospec(connector.gateway_class, instance=True)
    gateway.check_token.return_value = MicrosoftTokenInfo(app_name="Onyx Indexer")

    result = _run(connector, gateway)[connector.sign_in_id]

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Signed in as Onyx Indexer"
    assert result.validates_binding
