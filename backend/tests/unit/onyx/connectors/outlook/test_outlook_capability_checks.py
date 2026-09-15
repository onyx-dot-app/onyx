"""Behavior tests for the Outlook capability checks.

Each check runs against an autospecced ``OutlookSourceOperations`` whose
operations return the gateway's plain models. Probe reach (which operations a
check exercises) is enforced by the auto-discovering coverage harness.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.outlook.capability_checks import build_outlook_indexing_checks
from onyx.connectors.outlook.models import (
    INVALID_AUTHORITY_CODE,
    MISSING_CREDENTIAL_CODE,
    OutlookAuthError,
    OutlookDeltaPage,
    OutlookFolderPage,
    OutlookGraphError,
    OutlookMailboxPage,
    OutlookTokenInfo,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    CREDENTIALS,
    INBOX_ID,
    MAILBOX_ADDRESS,
    MAILBOX_ID,
    folder,
    graph_error,
    mailbox,
    message,
)

_CHECKS_BY_ID = {check.check_id: check for check in build_outlook_indexing_checks()}


def _gateway() -> MagicMock:
    """A healthy tenant: one user with a readable mailbox holding one message."""
    gateway = create_autospec(OutlookSourceOperations, instance=True)
    gateway.check_token.return_value = OutlookTokenInfo(expires_in=3599)
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(mailboxes=[mailbox()])
    gateway.resolve_mailbox.return_value = mailbox()
    gateway.probe_mailbox.return_value = folder()
    gateway.get_well_known_folder.return_value = folder(id="junk", display_name="Junk")
    gateway.list_child_folders.return_value = OutlookFolderPage(folders=[folder()])
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(changes=[])
    gateway.read_any_message.return_value = message()
    return gateway


def _context(
    gateway: MagicMock,
    connector_specific_config: dict[str, Any] | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.OUTLOOK,
        credential_json=CREDENTIALS,
        connector_specific_config=connector_specific_config,
        source_operations=gateway,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


# ---------------------------------------------------------------------------
# outlook_token_auth
# ---------------------------------------------------------------------------


def test_token_check_passes_on_a_token() -> None:
    _run("outlook_token_auth", _context(_gateway()))


def test_token_check_reports_a_blank_credential_field() -> None:
    gateway = _gateway()
    gateway.check_token.side_effect = OutlookAuthError(
        MISSING_CREDENTIAL_CODE, "missing outlook_client_secret"
    )

    with pytest.raises(CredentialInvalidError, match="outlook_client_secret"):
        _run("outlook_token_auth", _context(gateway))


@pytest.mark.parametrize(
    "code", ["invalid_client", "unauthorized_client", INVALID_AUTHORITY_CODE, "weird"]
)
def test_token_check_maps_msal_refusals_to_invalid_credential(code: str) -> None:
    gateway = _gateway()
    gateway.check_token.side_effect = OutlookAuthError(code, "nope")

    with pytest.raises(CredentialInvalidError):
        _run("outlook_token_auth", _context(gateway))


@pytest.mark.parametrize("code", ["temporarily_unavailable", "server_error"])
def test_token_check_is_indeterminate_on_a_transient_oauth_error(code: str) -> None:
    gateway = _gateway()
    gateway.check_token.side_effect = OutlookAuthError(code, "AADSTS90033 try later")

    with pytest.raises(UnexpectedValidationError):
        _run("outlook_token_auth", _context(gateway))


def test_token_check_is_indeterminate_when_the_token_endpoint_is_unreachable() -> None:
    gateway = _gateway()
    gateway.check_token.side_effect = OutlookGraphError(
        None, "ConnectionError", "login unreachable"
    )

    with pytest.raises(UnexpectedValidationError):
        _run("outlook_token_auth", _context(gateway))


# ---------------------------------------------------------------------------
# outlook_mailbox_listing
# ---------------------------------------------------------------------------


def test_listing_check_probes_one_user() -> None:
    gateway = _gateway()

    _run("outlook_mailbox_listing", _context(gateway))

    gateway.list_mailbox_users.assert_called_once_with(page_size=1)


def test_listing_check_names_the_missing_permission_on_403() -> None:
    gateway = _gateway()
    gateway.list_mailbox_users.side_effect = graph_error(
        403, "Authorization_RequestDenied"
    )

    with pytest.raises(InsufficientPermissionsError, match="User.Read.All"):
        _run("outlook_mailbox_listing", _context(gateway))


def test_listing_check_maps_401_to_expired_and_429_to_indeterminate() -> None:
    gateway = _gateway()
    gateway.list_mailbox_users.side_effect = graph_error(
        401, "InvalidAuthenticationToken"
    )
    with pytest.raises(CredentialExpiredError):
        _run("outlook_mailbox_listing", _context(gateway))

    gateway.list_mailbox_users.side_effect = graph_error(429, "TooManyRequests")
    with pytest.raises(UnexpectedValidationError):
        _run("outlook_mailbox_listing", _context(gateway))


# ---------------------------------------------------------------------------
# outlook_mail_read
# ---------------------------------------------------------------------------


def test_mail_read_check_probes_the_first_configured_mailbox() -> None:
    gateway = _gateway()

    _run(
        "outlook_mail_read",
        _context(gateway, {"mailboxes": ["bob@contoso.com", "carol@contoso.com"]}),
    )

    gateway.list_mailbox_users.assert_not_called()
    gateway.resolve_mailbox.assert_called_once_with(address="bob@contoso.com")
    gateway.fetch_folder_delta_page.assert_called_once_with(
        mailbox_id=MAILBOX_ID, folder_id=INBOX_ID, page_size=1
    )
    gateway.read_any_message.assert_called_once_with(mailbox_id=MAILBOX_ID)


def test_mail_read_check_falls_back_to_the_first_tenant_user() -> None:
    gateway = _gateway()

    _run("outlook_mail_read", _context(gateway))

    gateway.list_mailbox_users.assert_called_once_with(page_size=1, next_link=None)
    gateway.resolve_mailbox.assert_not_called()
    gateway.probe_mailbox.assert_called_once_with(mailbox_id=MAILBOX_ID)


def test_mail_read_check_skips_enabled_users_without_a_mailbox() -> None:
    """A directory sync service account is enabled but has no mailbox, and it
    is often the first user Graph lists."""
    gateway = _gateway()
    gateway.list_mailbox_users.side_effect = [
        OutlookMailboxPage(
            mailboxes=[mailbox(id="sync-svc", address="sync@contoso.com")],
            next_link="https://graph/users?page=2",
        ),
        OutlookMailboxPage(mailboxes=[mailbox()]),
    ]
    gateway.probe_mailbox.side_effect = [
        graph_error(404, "MailboxNotEnabledForRESTAPI"),
        folder(),
    ]

    _run("outlook_mail_read", _context(gateway))

    assert gateway.list_mailbox_users.call_args_list[1].kwargs["next_link"] == (
        "https://graph/users?page=2"
    )
    gateway.fetch_folder_delta_page.assert_called_once_with(
        mailbox_id=MAILBOX_ID, folder_id=INBOX_ID, page_size=1
    )


def test_mail_read_check_follows_an_empty_user_page() -> None:
    gateway = _gateway()
    gateway.list_mailbox_users.side_effect = [
        OutlookMailboxPage(mailboxes=[], next_link="https://graph/users?page=2"),
        OutlookMailboxPage(mailboxes=[mailbox()]),
    ]

    _run("outlook_mail_read", _context(gateway))

    assert gateway.list_mailbox_users.call_count == 2
    gateway.probe_mailbox.assert_called_once_with(mailbox_id=MAILBOX_ID)


def test_mail_read_check_is_indeterminate_when_no_user_has_a_mailbox() -> None:
    gateway = _gateway()
    gateway.probe_mailbox.side_effect = graph_error(404, "MailboxNotEnabledForRESTAPI")

    with pytest.raises(UnexpectedValidationError, match="List a mailbox"):
        _run("outlook_mail_read", _context(gateway))


def test_mail_read_check_is_indeterminate_for_a_mailbox_without_messages() -> None:
    """An empty mailbox proves nothing about body access, so the check must
    not report a pass."""
    gateway = _gateway()
    gateway.read_any_message.return_value = None

    with pytest.raises(UnexpectedValidationError, match="holds no messages"):
        _run("outlook_mail_read", _context(gateway))


def test_mail_read_check_tells_read_basic_apart_from_read() -> None:
    """Mail.ReadBasic.All answers every metadata probe and refuses only the body."""
    gateway = _gateway()
    gateway.read_any_message.side_effect = graph_error(403)

    with pytest.raises(InsufficientPermissionsError, match="Mail.ReadBasic.All"):
        _run("outlook_mail_read", _context(gateway))


def test_mail_read_check_is_indeterminate_without_any_user() -> None:
    gateway = _gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(mailboxes=[])

    with pytest.raises(UnexpectedValidationError):
        _run("outlook_mail_read", _context(gateway))


def test_mail_read_check_fails_when_the_address_matches_nobody() -> None:
    gateway = _gateway()
    gateway.resolve_mailbox.return_value = None

    with pytest.raises(ConnectorValidationError, match="No user matches"):
        _run(
            "outlook_mail_read", _context(gateway, {"mailboxes": ["ghost@contoso.com"]})
        )


def test_mail_read_check_points_at_the_exchange_scope_on_403() -> None:
    gateway = _gateway()
    gateway.probe_mailbox.side_effect = graph_error(403)

    with pytest.raises(InsufficientPermissionsError, match="Exchange"):
        _run("outlook_mail_read", _context(gateway))


def test_mail_read_check_reports_a_configured_mailbox_that_does_not_exist() -> None:
    gateway = _gateway()
    gateway.probe_mailbox.side_effect = graph_error(404, "MailboxNotEnabledForRESTAPI")

    with pytest.raises(ConnectorValidationError, match="MailboxNotEnabledForRESTAPI"):
        _run("outlook_mail_read", _context(gateway, {"mailboxes": [MAILBOX_ADDRESS]}))


# ---------------------------------------------------------------------------
# outlook_configured_mailboxes
# ---------------------------------------------------------------------------


def test_configured_check_does_nothing_in_every_mailbox_mode() -> None:
    gateway = _gateway()

    _run("outlook_configured_mailboxes", _context(gateway, {"mailboxes": []}))

    gateway.resolve_mailbox.assert_not_called()


def test_configured_check_lists_every_problem_address() -> None:
    gateway = _gateway()
    gateway.resolve_mailbox.side_effect = [
        None,
        mailbox(id="user-2"),
        mailbox(id="user-3"),
    ]
    gateway.probe_mailbox.side_effect = [graph_error(403), folder()]

    with pytest.raises(ConnectorValidationError) as exc_info:
        _run(
            "outlook_configured_mailboxes",
            _context(
                gateway,
                {
                    "mailboxes": [
                        "ghost@contoso.com",
                        "denied@contoso.com",
                        "ok@contoso.com",
                    ]
                },
            ),
        )

    message = str(exc_info.value)
    assert "ghost@contoso.com" in message
    assert "denied@contoso.com (ErrorAccessDenied)" in message
    assert "ok@contoso.com" not in message


def test_configured_check_probes_every_address_however_long_the_list() -> None:
    gateway = _gateway()
    addresses = [f"user{i}@contoso.com" for i in range(40)]
    gateway.resolve_mailbox.side_effect = [mailbox()] * 39 + [None]

    with pytest.raises(ConnectorValidationError, match="user39@contoso.com"):
        _run(
            "outlook_configured_mailboxes", _context(gateway, {"mailboxes": addresses})
        )

    assert gateway.resolve_mailbox.call_count == 40


def test_configured_check_does_not_blame_the_mailbox_for_a_throttled_probe() -> None:
    gateway = _gateway()
    gateway.probe_mailbox.side_effect = graph_error(503, "ServiceUnavailable")

    with pytest.raises(UnexpectedValidationError):
        _run(
            "outlook_configured_mailboxes",
            _context(gateway, {"mailboxes": [MAILBOX_ADDRESS]}),
        )


def test_configured_check_names_user_read_all_when_resolution_is_denied() -> None:
    gateway = _gateway()
    gateway.resolve_mailbox.side_effect = graph_error(
        403, "Authorization_RequestDenied"
    )

    with pytest.raises(InsufficientPermissionsError, match="User.Read.All"):
        _run(
            "outlook_configured_mailboxes",
            _context(gateway, {"mailboxes": [MAILBOX_ADDRESS]}),
        )


def test_configured_check_is_skipped_without_a_config() -> None:
    results = run_capability_checks(
        [_CHECKS_BY_ID["outlook_configured_mailboxes"]], _context(_gateway())
    )

    assert results[0].status is CapabilityCheckStatus.SKIPPED


# ---------------------------------------------------------------------------
# the set
# ---------------------------------------------------------------------------


def test_check_ids_are_unique() -> None:
    checks = build_outlook_indexing_checks()
    assert len({check.check_id for check in checks}) == len(checks)


def test_healthy_tenant_passes_indexing() -> None:
    results = run_capability_checks(
        build_outlook_indexing_checks(),
        _context(_gateway(), {"mailboxes": [MAILBOX_ADDRESS]}),
    )

    assert all(result.status is CapabilityCheckStatus.PASSED for result in results)
    verdicts = compute_capability_verdicts({CredentialCapability.INDEXING}, results)
    assert verdicts[CredentialCapability.INDEXING] is CapabilityVerdict.PASSED
