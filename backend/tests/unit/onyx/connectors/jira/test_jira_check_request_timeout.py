"""The Jira checks' request timeout: checks call the gateway with
``fast=True``, whose client times out each request and does not retry, and a
timeout gives the timed-out row. The default client that indexing uses keeps
the SDK's defaults (no timeout, 3 retries)."""

from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira import source_operations as jira_source_operations
from onyx.connectors.jira.capability_checks import build_jira_indexing_checks
from onyx.connectors.jira.source_operations import (
    JiraSourceOperations,
    JiraTimeoutError,
)

_SITE_URL = "https://example.atlassian.net"
_MYSELF_URL = f"{_SITE_URL}/rest/api/3/myself"
_CLOUD_CREDENTIAL = {"jira_user_email": "bot@example.com", "jira_api_token": "t"}
_SIGN_IN_DESCRIPTION = (
    "Jira did not answer the sign-in in time.\n"
    "Re-run, or check that Jira is reachable from Onyx."
)


def _read_timeout() -> requests.ReadTimeout:
    request = requests.Request("GET", _MYSELF_URL).prepare()
    return requests.ReadTimeout("Read timed out. (read timeout=10)", request=request)


def _timeout_error() -> JiraTimeoutError:
    return JiraTimeoutError(
        "Jira did not answer within 10s.",
        status_code=None,
        method="GET",
        url=_MYSELF_URL,
    )


def _real_gateway() -> JiraSourceOperations:
    return JiraSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, DocumentSource.JIRA.value, _CLOUD_CREDENTIAL
        ),
        connector_specific_config={"jira_base_url": _SITE_URL},
    )


def _mock_gateway() -> MagicMock:
    gateway: MagicMock = create_autospec(JiraSourceOperations, instance=True)
    gateway._is_cloud.return_value = True
    return gateway


def _run(
    check_id: str,
    gateway: MagicMock,
    *,
    form_run: bool,
    **config: Any,
) -> CapabilityCheckResult:
    checks = [
        check for check in build_jira_indexing_checks() if check.check_id == check_id
    ]
    context = CapabilityCheckContext(
        source=DocumentSource.JIRA,
        credential_json=_CLOUD_CREDENTIAL,
        connector_specific_config={"jira_base_url": _SITE_URL, **config},
        source_operations=gateway,
    )
    (result,) = run_capability_checks(checks, context, form_run=form_run)
    return result


# --- the gateway ---


def test_the_fast_client_times_out_requests_and_does_not_retry() -> None:
    with patch.object(jira_source_operations, "JIRA") as jira_class:
        _real_gateway().get_myself(fast=True)

    kwargs: Mapping[str, Any] = jira_class.call_args.kwargs
    assert kwargs["timeout"] == 10
    assert kwargs["max_retries"] == 0


def test_the_indexing_client_keeps_the_sdk_defaults() -> None:
    with patch.object(jira_source_operations, "JIRA") as jira_class:
        _real_gateway().get_myself()

    kwargs: Mapping[str, Any] = jira_class.call_args.kwargs
    assert kwargs["timeout"] is None
    assert kwargs["max_retries"] == 3


def test_the_fast_and_indexing_clients_are_cached_apart() -> None:
    gateway: JiraSourceOperations = _real_gateway()
    with patch.object(jira_source_operations, "JIRA") as jira_class:
        jira_class.side_effect = [MagicMock(name="fast"), MagicMock(name="indexing")]
        gateway.get_myself(fast=True)
        gateway.get_myself(fast=True)
        gateway.get_myself()
        gateway.get_myself()

    assert jira_class.call_count == 2
    assert gateway._cached_fast_client is not gateway._cached_client


def test_a_fast_call_raises_a_typed_timeout_with_the_request() -> None:
    gateway: JiraSourceOperations = _real_gateway()
    client = MagicMock()
    client.myself.side_effect = _read_timeout()
    gateway._cached_fast_client = client

    with pytest.raises(JiraTimeoutError) as raised:
        gateway.get_myself(fast=True)

    assert raised.value.status_code is None
    assert raised.value.method == "GET"
    assert raised.value.url == _MYSELF_URL


def test_an_indexing_call_raises_the_timeout_unchanged() -> None:
    gateway: JiraSourceOperations = _real_gateway()
    client = MagicMock()
    client.myself.side_effect = _read_timeout()
    gateway._cached_client = client

    with pytest.raises(requests.ReadTimeout):
        gateway.get_myself()


# --- the checks ---


def test_the_checks_call_the_fast_client() -> None:
    gateway: MagicMock = _mock_gateway()
    gateway.get_myself.return_value = {"displayName": "Onyx Bot"}

    _run("jira_auth", gateway, form_run=True)

    gateway.get_myself.assert_called_once_with(fast=True)


@pytest.mark.parametrize(
    ("form_run", "status"),
    [
        (True, CapabilityCheckStatus.FAILED),
        (False, CapabilityCheckStatus.INCOMPLETE),
    ],
)
def test_a_sign_in_timeout_fails_only_a_form_run(
    form_run: bool, status: CapabilityCheckStatus
) -> None:
    gateway: MagicMock = _mock_gateway()
    gateway.get_myself.side_effect = _timeout_error()

    result: CapabilityCheckResult = _run("jira_auth", gateway, form_run=form_run)

    assert result.status == status
    assert result.summary == "Sign-in timed out"
    assert result.description == _SIGN_IN_DESCRIPTION
    assert result.error_kind == CheckErrorKind.UNREACHABLE
    assert result.error_detail is not None
    assert result.error_detail.request == "GET example.atlassian.net/rest/api/3/myself"


def test_a_scoped_site_lookup_timeout_is_a_sign_in_timeout() -> None:
    gateway: MagicMock = _mock_gateway()
    gateway.list_projects.side_effect = requests.ConnectTimeout("tenant_info")

    result: CapabilityCheckResult = _run(
        "jira_scoped_token_auth", gateway, form_run=True, scoped_token=True
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Sign-in timed out"


def test_a_refused_connection_still_cannot_reach_jira() -> None:
    gateway: MagicMock = _mock_gateway()
    gateway.get_myself.side_effect = requests.ConnectionError("refused")

    result: CapabilityCheckResult = _run("jira_auth", gateway, form_run=True)

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.summary == "Cannot reach Jira"


def test_a_timeout_after_sign_in_is_incomplete_on_a_form_run() -> None:
    gateway: MagicMock = _mock_gateway()
    gateway.list_projects.side_effect = _timeout_error()

    result: CapabilityCheckResult = _run(
        "jira_projects_visible", gateway, form_run=True
    )

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.summary == "Timed out"
    assert result.description == (
        "The check stopped because Jira did not answer in time.\nRe-run the checks."
    )
