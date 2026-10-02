"""Behavior tests for the Confluence permission-sync and group-sync checks.

Every test runs a check against an autospecced ``ConfluenceSourceOperations``
with the config the web form sends.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
import requests
from requests import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CredentialCapability,
    compute_capability_verdicts,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.confluence import capability_checks
from onyx.connectors.confluence.capability_checks import (
    build_confluence_doc_permission_sync_checks,
    build_confluence_group_sync_checks,
)
from onyx.connectors.confluence.connector import (
    PER_PAGE_RESTRICTIONS_EXPANSION_FIELDS,
    RESTRICTIONS_EXPANSION_FIELDS,
)
from onyx.connectors.confluence.models import ConfluenceUser
from onyx.connectors.confluence.source_operations import (
    Confcloud77618Error,
    ConfluenceRestSpacePermissionsNotAvailableError,
    ConfluenceSourceOperations,
    ConfluenceSpaceNotFoundError,
    ConfluenceSpacePermissionsVariant,
    ConfluenceUserEmailVariant,
    ConfluenceUserListVariant,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.db.enums import AccessType

_WIKI_BASE = "https://acme.atlassian.net/wiki"
_DPS_CHECKS = build_confluence_doc_permission_sync_checks()
_EGS_CHECKS = build_confluence_group_sync_checks()
_CHECKS_BY_ID: dict[str, CapabilityCheck] = {
    check.check_id: check for check in _DPS_CHECKS + _EGS_CHECKS
}
_OAUTH_CREDENTIAL = {"confluence_refresh_token": "refresh"}

_RESTRICTIONS = {
    "read": {
        "operation": "read",
        "restrictions": {"user": {"results": []}, "group": {"results": []}},
    }
}
_PAGE: dict[str, Any] = {"id": "42", "restrictions": _RESTRICTIONS, "ancestors": []}
_CLOUD_PERMISSIONS = [
    {
        "operation": {"operation": "read", "targetType": "space"},
        "subjects": {
            "user": {
                "results": [
                    {"accountId": "a-1", "accountType": "atlassian", "email": "a@x.io"}
                ]
            }
        },
    },
    {
        "operation": {"operation": "read", "targetType": "space"},
        "subjects": {"group": {"results": [{"name": "confluence-users"}]}},
    },
]
_DC_REST_PERMISSIONS = [
    {
        "operation": {"operationKey": "read", "targetType": "space"},
        "subject": {"type": "user", "userKey": "key-1"},
    },
    {
        "operation": {"operationKey": "read", "targetType": "space"},
        "subject": {"type": "group", "name": "confluence-users"},
    },
]
_DC_JSONRPC_PERMISSIONS = [
    {"type": "VIEWSPACE", "spacePermissions": [{"userName": "alice"}]},
]
_PERSON = ConfluenceUser(
    user_id="a-1", username="alice", display_name="Alice", email="a@x.io", type="user"
)
_APP = ConfluenceUser(
    user_id="app-1", username=None, display_name="Bot", email=None, type="app"
)


def _form(**overrides: Any) -> dict[str, Any]:
    return {
        "wiki_base": _WIKI_BASE,
        "is_cloud": True,
        "scoped_token": False,
        "space": "",
        "page_id": "",
        "index_recursively": True,
        "cql_query": "",
        "include_attachments": True,
        **overrides,
    }


def _http_error(status: int) -> HTTPError:
    response = requests.Response()
    response.status_code = status
    response.url = f"{_WIKI_BASE}/rest/api"
    response.reason = "Mock"
    response._content = b'{"message": "mock detail"}'
    return HTTPError(response=response)


def _gateway() -> MagicMock:
    gateway = create_autospec(ConfluenceSourceOperations, instance=True)
    gateway.list_spaces.side_effect = lambda **_: iter([{"key": "KB"}])
    gateway.search_pages_with_restrictions.side_effect = lambda **_: iter([dict(_PAGE)])
    gateway.search_attachments_with_restrictions.side_effect = lambda **_: iter([])
    gateway.get_content_read_restrictions.return_value = _RESTRICTIONS
    gateway.get_server_version.return_value = (9, 2)
    gateway.get_anonymous_space_permissions.return_value = []
    gateway.get_user_email.return_value = "a@x.io"
    gateway.get_listed_user_email.return_value = "a@x.io"
    gateway.list_users.side_effect = lambda **_: iter([_APP, _PERSON])
    gateway.list_user_groups.side_effect = lambda **_: iter(
        [{"name": "confluence-users"}]
    )

    def space_permissions(
        *, variant: ConfluenceSpacePermissionsVariant, **_: Any
    ) -> list[dict[str, Any]]:
        return {
            ConfluenceSpacePermissionsVariant.CLOUD: _CLOUD_PERMISSIONS,
            ConfluenceSpacePermissionsVariant.DC_REST: _DC_REST_PERMISSIONS,
            ConfluenceSpacePermissionsVariant.DC_JSONRPC: _DC_JSONRPC_PERMISSIONS,
        }[variant]

    gateway.get_space_permissions.side_effect = space_permissions
    return gateway


def _context(
    gateway: MagicMock,
    config: dict[str, Any] | None = None,
    credential_json: dict[str, Any] | None = None,
    access_type: AccessType | None = None,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.CONFLUENCE,
        credential_json=credential_json or {},
        connector_specific_config=config if config is not None else _form(),
        source_operations=gateway,
        access_type=access_type,
    )


def _run(check_id: str, context: CapabilityCheckContext) -> None:
    _CHECKS_BY_ID[check_id].run(context)


def _variants(gateway: MagicMock) -> list[ConfluenceSpacePermissionsVariant]:
    return [
        call.kwargs["variant"] for call in gateway.get_space_permissions.call_args_list
    ]


# Applicability


@pytest.mark.parametrize("is_cloud", [True, False], ids=["cloud", "dc"])
def test_full_runs_pass_and_select_the_deployment(is_cloud: bool) -> None:
    gateway = _gateway()
    context = _context(gateway, _form(is_cloud=is_cloud))

    results = run_capability_checks(_DPS_CHECKS + _EGS_CHECKS, context)

    by_id = {result.check_id: result for result in results}
    applicable = {result.check_id for result in results if result.applicable}
    assert all(
        by_id[check_id].status == CapabilityCheckStatus.PASSED
        for check_id in applicable
    ), {r.check_id: r.message for r in results if r.applicable}
    cloud_only = {
        "confluence_space_permissions_read",
        "confluence_permission_user_emails",
        "confluence_user_listing",
        "confluence_group_membership",
        "confluence_group_user_emails",
    }
    dc_only = {
        "confluence_space_permissions_read_dc_rest",
        "confluence_space_permissions_read_dc_jsonrpc",
        "confluence_permission_user_emails_dc",
        "confluence_anonymous_space_access",
        "confluence_user_listing_dc",
        "confluence_group_membership_dc",
        "confluence_group_user_emails_dc",
    }
    assert (cloud_only <= applicable) == is_cloud
    assert (dc_only <= applicable) == (not is_cloud)
    assert not (cloud_only if not is_cloud else dc_only) & applicable
    verdicts = compute_capability_verdicts(
        {
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        results,
    )
    assert (
        verdicts[CredentialCapability.DOC_PERMISSION_SYNC] == CapabilityVerdict.PASSED
    )
    assert (
        verdicts[CredentialCapability.EXTERNAL_GROUP_SYNC] == CapabilityVerdict.PASSED
    )


def test_checks_wait_for_the_site_fields() -> None:
    for check in _DPS_CHECKS + _EGS_CHECKS:
        assert check.requires_fields == frozenset({"wiki_base", "is_cloud"})


@pytest.mark.parametrize(
    "access_type,applicable",
    [(AccessType.SYNC, True), (AccessType.PUBLIC, False), (AccessType.PRIVATE, False)],
)
def test_checks_apply_only_to_perm_synced_access(
    access_type: AccessType, applicable: bool
) -> None:
    context = _context(_gateway(), access_type=access_type)

    results = run_capability_checks(_DPS_CHECKS + _EGS_CHECKS, context)

    assert any(result.applicable for result in results) == applicable


# confluence_page_restrictions_read / confluence_restrictions_batch_read


def test_restrictions_read_probes_page_attachment_and_per_page_lookup() -> None:
    gateway = _gateway()

    _run("confluence_page_restrictions_read", _context(gateway))

    expand = gateway.search_pages_with_restrictions.call_args.kwargs["expand"]
    assert expand == ",".join(RESTRICTIONS_EXPANSION_FIELDS)
    gateway.get_content_read_restrictions.assert_called_once_with(content_id="42")
    assert gateway.search_attachments_with_restrictions.call_args.kwargs[
        "expand"
    ] == ",".join(RESTRICTIONS_EXPANSION_FIELDS)


def test_restrictions_read_skips_attachments_when_they_are_off() -> None:
    gateway = _gateway()

    _run(
        "confluence_page_restrictions_read",
        _context(gateway, _form(include_attachments=False)),
    )

    gateway.search_attachments_with_restrictions.assert_not_called()


def test_restrictions_read_names_the_oauth_scope_on_403() -> None:
    gateway = _gateway()
    gateway.search_pages_with_restrictions.side_effect = _http_error(403)

    with pytest.raises(
        InsufficientPermissionsError, match="read:confluence-content.permission"
    ):
        _run(
            "confluence_page_restrictions_read",
            _context(gateway, credential_json=_OAUTH_CREDENTIAL),
        )


def test_restrictions_read_fails_when_the_expand_is_dropped() -> None:
    gateway = _gateway()
    gateway.search_pages_with_restrictions.side_effect = lambda **_: iter(
        [{"id": "42"}]
    )

    with pytest.raises(InsufficientPermissionsError, match="read restrictions"):
        _run("confluence_page_restrictions_read", _context(gateway))


def test_restrictions_read_fails_when_the_per_page_lookup_is_denied() -> None:
    gateway = _gateway()
    gateway.get_content_read_restrictions.return_value = None

    with pytest.raises(InsufficientPermissionsError, match="byOperation"):
        _run("confluence_page_restrictions_read", _context(gateway))


def _fail_fast_expand(**kwargs: Any) -> Any:
    if kwargs["expand"] == ",".join(RESTRICTIONS_EXPANSION_FIELDS):
        raise Confcloud77618Error(url="/rest/api/content/search", body="No content")
    return iter([dict(_PAGE)])


def test_confcloud_77618_passes_with_the_per_page_fallback() -> None:
    gateway = _gateway()
    gateway.search_pages_with_restrictions.side_effect = _fail_fast_expand

    _run("confluence_page_restrictions_read", _context(gateway))

    expands = [
        call.kwargs["expand"]
        for call in gateway.search_pages_with_restrictions.call_args_list
    ]
    assert expands[-1] == ",".join(PER_PAGE_RESTRICTIONS_EXPANSION_FIELDS)


def test_confcloud_77618_is_a_warning_not_a_failure() -> None:
    gateway = _gateway()
    gateway.search_pages_with_restrictions.side_effect = _fail_fast_expand
    context = _context(gateway)

    results = run_capability_checks(_DPS_CHECKS, context)

    by_id = {result.check_id: result for result in results}
    batch = by_id["confluence_restrictions_batch_read"]
    assert batch.status == CapabilityCheckStatus.FAILED
    assert not batch.required
    assert "CONFCLOUD-77618" in batch.message
    assert (
        by_id["confluence_page_restrictions_read"].status
        == CapabilityCheckStatus.PASSED
    )
    verdicts = compute_capability_verdicts(
        {CredentialCapability.DOC_PERMISSION_SYNC}, results
    )
    assert (
        verdicts[CredentialCapability.DOC_PERMISSION_SYNC]
        == CapabilityVerdict.PASSED_WITH_WARNINGS
    )


# confluence_space_permissions_read (Cloud)


def test_cloud_space_permissions_probe_the_configured_space() -> None:
    gateway = _gateway()

    _run("confluence_space_permissions_read", _context(gateway, _form(space="ENG")))

    gateway.list_spaces.assert_not_called()
    gateway.get_space_permissions.assert_called_once_with(
        variant=ConfluenceSpacePermissionsVariant.CLOUD, space_key="ENG"
    )


def test_cloud_space_permissions_probe_the_first_space_otherwise() -> None:
    gateway = _gateway()

    _run(
        "confluence_space_permissions_read",
        _context(gateway, _form(space="ENG", cql_query="type=page")),
    )

    assert gateway.get_space_permissions.call_args.kwargs["space_key"] == "KB"


def test_cloud_space_permissions_without_subjects_need_space_admin() -> None:
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = None
    gateway.get_space_permissions.return_value = [
        {"operation": {"operation": "read"}, "anonymousAccess": False}
    ]

    with pytest.raises(InsufficientPermissionsError, match="space admin"):
        _run("confluence_space_permissions_read", _context(gateway))


def test_cloud_space_permissions_hidden_space_fails() -> None:
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = ConfluenceSpaceNotFoundError("x")

    with pytest.raises(ConnectorValidationError, match="not visible"):
        _run("confluence_space_permissions_read", _context(gateway))


# confluence_space_permissions_read_dc_rest / _dc_jsonrpc


def test_dc_rest_500_means_not_admin() -> None:
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = InsufficientPermissionsError("500")

    with pytest.raises(InsufficientPermissionsError, match="CONFSERVER-99908"):
        _run(
            "confluence_space_permissions_read_dc_rest",
            _context(gateway, _form(is_cloud=False)),
        )


def test_dc_rest_missing_api_passes() -> None:
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = (
        ConfluenceRestSpacePermissionsNotAvailableError("404")
    )

    _run(
        "confluence_space_permissions_read_dc_rest",
        _context(gateway, _form(is_cloud=False)),
    )


@pytest.mark.parametrize("version", [(8, 9), None], ids=["before_91", "unknown"])
def test_dc_rest_check_passes_where_sync_uses_jsonrpc(
    version: tuple[int, int] | None,
) -> None:
    gateway = _gateway()
    gateway.get_server_version.return_value = version

    _run(
        "confluence_space_permissions_read_dc_rest",
        _context(gateway, _form(is_cloud=False)),
    )

    gateway.get_space_permissions.assert_not_called()


def test_dc_jsonrpc_is_not_used_on_91_plus() -> None:
    gateway = _gateway()

    _run(
        "confluence_space_permissions_read_dc_jsonrpc",
        _context(gateway, _form(is_cloud=False)),
    )

    assert _variants(gateway) == [ConfluenceSpacePermissionsVariant.DC_REST]


@pytest.mark.parametrize("version", [(8, 9), None], ids=["before_91", "unknown"])
def test_dc_jsonrpc_is_used_before_91(version: tuple[int, int] | None) -> None:
    gateway = _gateway()
    gateway.get_server_version.return_value = version

    _run(
        "confluence_space_permissions_read_dc_jsonrpc",
        _context(gateway, _form(is_cloud=False)),
    )

    assert _variants(gateway) == [ConfluenceSpacePermissionsVariant.DC_JSONRPC]


def test_dc_jsonrpc_is_the_fallback_for_a_missing_rest_api() -> None:
    gateway = _gateway()

    def space_permissions(
        *, variant: ConfluenceSpacePermissionsVariant, **_: Any
    ) -> list[dict[str, Any]]:
        if variant == ConfluenceSpacePermissionsVariant.DC_REST:
            raise ConfluenceRestSpacePermissionsNotAvailableError("404")
        return _DC_JSONRPC_PERMISSIONS

    gateway.get_space_permissions.side_effect = space_permissions

    _run(
        "confluence_space_permissions_read_dc_jsonrpc",
        _context(gateway, _form(is_cloud=False)),
    )

    assert _variants(gateway) == [
        ConfluenceSpacePermissionsVariant.DC_REST,
        ConfluenceSpacePermissionsVariant.DC_JSONRPC,
    ]


def test_dc_jsonrpc_401_means_remote_api_off() -> None:
    gateway = _gateway()
    gateway.get_server_version.return_value = (8, 9)
    gateway.get_space_permissions.side_effect = _http_error(401)

    with pytest.raises(ConnectorValidationError, match="Remote API"):
        _run(
            "confluence_space_permissions_read_dc_jsonrpc",
            _context(gateway, _form(is_cloud=False)),
        )


def test_dc_jsonrpc_websudo_html_fails() -> None:
    gateway = _gateway()
    gateway.get_server_version.return_value = (8, 9)
    gateway.get_space_permissions.side_effect = ConnectorValidationError(
        "non-JSON response ... WebSudo"
    )

    with pytest.raises(ConnectorValidationError, match="WebSudo"):
        _run(
            "confluence_space_permissions_read_dc_jsonrpc",
            _context(gateway, _form(is_cloud=False)),
        )


def test_dc_jsonrpc_empty_result_needs_admin() -> None:
    gateway = _gateway()
    gateway.get_server_version.return_value = (8, 9)
    gateway.get_space_permissions.side_effect = None
    gateway.get_space_permissions.return_value = []

    with pytest.raises(InsufficientPermissionsError, match="space admin"):
        _run(
            "confluence_space_permissions_read_dc_jsonrpc",
            _context(gateway, _form(is_cloud=False)),
        )


# confluence_permission_user_emails / _dc


def test_cloud_hidden_permission_emails_fail() -> None:
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = None
    gateway.get_space_permissions.return_value = [
        {
            "subjects": {
                "user": {
                    "results": [
                        {"accountId": "a-1", "accountType": "atlassian"},
                        {"accountId": "b-1", "accountType": "app", "email": "b@x"},
                    ]
                }
            }
        }
    ]

    with pytest.raises(InsufficientPermissionsError, match="visible email"):
        _run("confluence_permission_user_emails", _context(gateway))


def test_cloud_permission_emails_read_the_first_user_of_each_permission() -> None:
    # Permission sync maps only the first user of a permission.
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = None
    gateway.get_space_permissions.return_value = [
        {
            "subjects": {
                "user": {
                    "results": [
                        {"accountId": "a-1", "accountType": "atlassian"},
                        {
                            "accountId": "b-1",
                            "accountType": "atlassian",
                            "email": "b@x",
                        },
                    ]
                }
            }
        }
    ]

    with pytest.raises(InsufficientPermissionsError, match="visible email"):
        _run("confluence_permission_user_emails", _context(gateway))


@pytest.mark.parametrize(
    "version,variant,user",
    [
        ((9, 2), ConfluenceUserEmailVariant.USERKEY, "key-1"),
        ((8, 9), ConfluenceUserEmailVariant.USERNAME, "alice"),
    ],
    ids=["rest", "jsonrpc"],
)
def test_dc_permission_emails_use_the_lookup_of_the_api_in_use(
    version: tuple[int, int],
    variant: ConfluenceUserEmailVariant,
    user: str,
) -> None:
    gateway = _gateway()
    gateway.get_server_version.return_value = version

    _run(
        "confluence_permission_user_emails_dc",
        _context(gateway, _form(is_cloud=False)),
    )

    gateway.get_user_email.assert_called_once_with(
        variant=variant, user=user, cached=False
    )


def test_dc_unresolved_permission_emails_fail() -> None:
    gateway = _gateway()
    gateway.get_user_email.return_value = None

    with pytest.raises(InsufficientPermissionsError, match="Email address visibility"):
        _run(
            "confluence_permission_user_emails_dc",
            _context(gateway, _form(is_cloud=False)),
        )


def test_dc_permission_emails_wait_for_readable_permissions() -> None:
    gateway = _gateway()
    gateway.get_space_permissions.side_effect = InsufficientPermissionsError("500")

    with pytest.raises(UnexpectedValidationError):
        _run(
            "confluence_permission_user_emails_dc",
            _context(gateway, _form(is_cloud=False)),
        )


# confluence_anonymous_space_access


def test_anonymous_access_500_means_not_admin() -> None:
    gateway = _gateway()
    gateway.get_anonymous_space_permissions.side_effect = InsufficientPermissionsError(
        "500"
    )

    with pytest.raises(InsufficientPermissionsError, match="CONFSERVER-99908"):
        _run(
            "confluence_anonymous_space_access",
            _context(gateway, _form(is_cloud=False)),
        )


# Group sync


@pytest.mark.parametrize(
    "check_id,is_cloud,variant",
    [
        ("confluence_user_listing", True, ConfluenceUserListVariant.CLOUD),
        ("confluence_user_listing_dc", False, ConfluenceUserListVariant.DC),
    ],
)
def test_user_listing_uses_the_deployment_variant(
    check_id: str, is_cloud: bool, variant: ConfluenceUserListVariant
) -> None:
    gateway = _gateway()

    _run(check_id, _context(gateway, _form(is_cloud=is_cloud)))

    assert gateway.list_users.call_args.kwargs["variant"] == variant


def test_empty_user_listing_fails() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = lambda **_: iter([])

    with pytest.raises(InsufficientPermissionsError, match="listed no users"):
        _run("confluence_user_listing", _context(gateway))


def test_user_listing_names_the_oauth_scope_on_403() -> None:
    gateway = _gateway()
    gateway.list_users.side_effect = _http_error(403)

    with pytest.raises(InsufficientPermissionsError, match="read:confluence-user"):
        _run(
            "confluence_user_listing",
            _context(gateway, credential_json=_OAUTH_CREDENTIAL),
        )


def test_group_membership_reads_a_person_before_apps() -> None:
    gateway = _gateway()

    _run("confluence_group_membership", _context(gateway))

    gateway.list_user_groups.assert_called_once_with(user_id="a-1")


def test_group_membership_without_groups_is_indeterminate() -> None:
    # Group sync reads every user, so ungrouped sampled users prove nothing.
    gateway = _gateway()
    gateway.list_user_groups.side_effect = lambda **_: iter([])

    with pytest.raises(UnexpectedValidationError, match="read:confluence-groups"):
        _run(
            "confluence_group_membership",
            _context(gateway, credential_json=_OAUTH_CREDENTIAL),
        )


def test_cloud_group_users_without_emails_fail() -> None:
    gateway = _gateway()
    hidden = _PERSON.model_copy(update={"email": None})
    gateway.list_users.side_effect = lambda **_: iter([_APP, hidden])

    with pytest.raises(InsufficientPermissionsError, match="has an email"):
        _run("confluence_group_user_emails", _context(gateway))


def test_cloud_group_user_emails_read_every_listed_person() -> None:
    gateway = _gateway()
    hidden = _PERSON.model_copy(update={"email": None})
    gateway.list_users.side_effect = lambda **_: iter([hidden] * 10 + [_PERSON])

    _run("confluence_group_user_emails", _context(gateway))


def test_dc_group_user_emails_use_the_lookup() -> None:
    gateway = _gateway()
    dc_user = _PERSON.model_copy(update={"email": None})
    gateway.list_users.side_effect = lambda **_: iter([dc_user])

    _run("confluence_group_user_emails_dc", _context(gateway, _form(is_cloud=False)))

    gateway.get_listed_user_email.assert_called_once_with(
        username="alice", cached=False
    )


def test_dc_group_user_emails_read_the_profile_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capability_checks,
        "CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE",
        [{"user_id": "a-1", "email": "a@x.io"}],
    )
    gateway = _gateway()
    # The gateway lists the override profiles; the lookup must not be used.
    gateway.get_listed_user_email.return_value = "lookup@x.io"
    gateway.list_users.side_effect = lambda **_: iter([_PERSON])

    _run("confluence_group_user_emails_dc", _context(gateway, _form(is_cloud=False)))

    no_email = _PERSON.model_copy(update={"email": None})
    gateway.list_users.side_effect = lambda **_: iter([no_email])
    with pytest.raises(InsufficientPermissionsError, match="has an email"):
        _run(
            "confluence_group_user_emails_dc",
            _context(gateway, _form(is_cloud=False)),
        )
    gateway.get_listed_user_email.assert_not_called()
