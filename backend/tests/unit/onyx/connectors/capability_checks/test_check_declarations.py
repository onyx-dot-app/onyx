"""How the runner applies a check's declarations, and that every registered
check declares fields its source's config model has."""

from collections.abc import Callable
from typing import Any

import pytest

from ee.onyx.connectors.capability_checks import get_perm_sync_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CredentialCapability,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks, run_order
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.enums import AccessType


class _ChannelsCheck(CapabilityCheck[SlackConnectorConfig]):
    config_class = SlackConnectorConfig

    def __init__(
        self,
        *,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_fields: frozenset[str] = frozenset({"channels"}),
        applies: Callable[[FormState[SlackConnectorConfig]], bool] | None = None,
        access_types: frozenset[AccessType] | None = None,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id="test_channels",
            display_name="Channels",
            requires_connector_instance=False,
            requires_fields=requires_fields,
            access_types=access_types,
        )
        self._applies = applies
        self.seen_channels: list[str] | None = None

    def applies(self, form_state: FormState[SlackConnectorConfig]) -> bool:
        return self._applies(form_state) if self._applies else True

    def run(self, context: CapabilityCheckContext) -> None:
        self.seen_channels = self.config(context).channels


def _run(
    check: _ChannelsCheck,
    config: dict[str, Any] | None,
    access_type: AccessType | None = None,
) -> CapabilityCheckStatus:
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector_specific_config=config,
        access_type=access_type,
    )
    (result,) = run_capability_checks([check], context)
    return result.status


def test_check_reads_its_declared_fields_typed() -> None:
    check = _ChannelsCheck()

    assert _run(check, {"channels": ["eng"]}) == CapabilityCheckStatus.PASSED
    assert check.seen_channels == ["eng"]


def test_missing_declared_field_skips_and_names_it() -> None:
    check = _ChannelsCheck()
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector_specific_config={"channel_regex_enabled": True},
    )

    (result,) = run_capability_checks([check], context)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert "channels" in result.message
    assert check.seen_channels is None


def test_invalid_field_fails_before_the_check_runs() -> None:
    check = _ChannelsCheck()

    assert (
        _run(check, {"channels": ["eng"], "batch_size": "x"})
        == CapabilityCheckStatus.FAILED
    )
    assert check.seen_channels is None


def test_unknown_keys_do_not_fail_the_check() -> None:
    check = _ChannelsCheck()

    assert (
        _run(check, {"channels": ["eng"], "removed_field": True})
        == CapabilityCheckStatus.PASSED
    )


def test_applies_false_skips() -> None:
    check = _ChannelsCheck(applies=lambda form_state: not form_state.config.channels)
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector_specific_config={"channels": ["eng"]},
    )

    (result,) = run_capability_checks([check], context)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert not result.applicable


def test_missing_field_skip_still_applies() -> None:
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector_specific_config={"channel_regex_enabled": True},
    )

    (result,) = run_capability_checks([_ChannelsCheck()], context)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.applicable


def test_config_less_run_skips_a_config_reading_check() -> None:
    assert _run(_ChannelsCheck(), None) == CapabilityCheckStatus.SKIPPED


@pytest.mark.parametrize(
    "access_type,expected",
    [
        (None, CapabilityCheckStatus.PASSED),
        (AccessType.SYNC, CapabilityCheckStatus.PASSED),
        (AccessType.SYNC_RESTRICTED, CapabilityCheckStatus.PASSED),
        (AccessType.PRIVATE, CapabilityCheckStatus.SKIPPED),
        (AccessType.PUBLIC, CapabilityCheckStatus.SKIPPED),
    ],
)
def test_perm_sync_checks_apply_to_perm_synced_access_types(
    access_type: AccessType | None, expected: CapabilityCheckStatus
) -> None:
    check = _ChannelsCheck(capability=CredentialCapability.DOC_PERMISSION_SYNC)

    assert _run(check, {"channels": ["eng"]}, access_type) == expected


def test_access_type_exclusion_does_not_apply() -> None:
    check = _ChannelsCheck(capability=CredentialCapability.DOC_PERMISSION_SYNC)
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK,
        credential_json={},
        connector_specific_config={"channels": ["eng"]},
        access_type=AccessType.PUBLIC,
    )

    (result,) = run_capability_checks([check], context)

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert not result.applicable


def test_perm_sync_check_can_apply_to_every_access_type() -> None:
    check = _ChannelsCheck(
        capability=CredentialCapability.DOC_PERMISSION_SYNC,
        access_types=frozenset(AccessType),
    )

    assert _run(check, {"channels": ["eng"]}, AccessType.PUBLIC) == (
        CapabilityCheckStatus.PASSED
    )


def _registered_checks(source: DocumentSource) -> list[CapabilityCheck[Any]]:
    return [*get_capability_checks(source), *get_perm_sync_capability_checks(source)]


@pytest.mark.parametrize("source", sorted(CONNECTOR_CLASS_MAP, key=str))
def test_checks_declare_fields_of_their_source_config(source: DocumentSource) -> None:
    source_config_class = CONNECTOR_CLASS_MAP[source].config_class
    for check in _registered_checks(source):
        if check.config_class is not None:
            assert check.config_class is source_config_class, check.check_id
        if check.requires_fields:
            assert check.config_class is not None, check.check_id
            assert check.requires_fields <= set(source_config_class.model_fields), (
                check.check_id
            )


@pytest.mark.parametrize("source", sorted(CONNECTOR_CLASS_MAP, key=str))
def test_binding_checks_require_only_bound_fields(source: DocumentSource) -> None:
    # The create form runs these checks before the rest of the config is
    # filled, so they can wait only for the credential-bound fields.
    binding_class = CONNECTOR_CLASS_MAP[source].config_class.credential_binding_class()
    for check in _registered_checks(source):
        if not check.validates_binding:
            continue
        bound_fields = set(binding_class.model_fields) if binding_class else set()
        assert check.requires_fields <= bound_fields, check.check_id


@pytest.mark.parametrize("source", sorted(CONNECTOR_CLASS_MAP, key=str))
def test_dependencies_name_registered_checks_without_a_cycle(
    source: DocumentSource,
) -> None:
    checks = _registered_checks(source)
    check_ids = {check.check_id for check in checks}
    # Discovery checks start after every validation check, so none can be a
    # validation check's dependency.
    discovery_ids = {check.check_id for check in checks if check.discovery}
    for check in checks:
        assert set(check.dependency_ids) <= check_ids, check.check_id
        assert check.check_id not in check.dependency_ids, check.check_id
        if not check.discovery:
            assert not discovery_ids & set(check.dependency_ids), check.check_id
    # Raises on a cycle.
    run_order(checks)


def test_confluence_declares_its_binding_checks() -> None:
    assert {
        check.check_id
        for check in _registered_checks(DocumentSource.CONFLUENCE)
        if check.validates_binding
    } == {
        "confluence_auth",
        "confluence_scoped_token_auth",
        "confluence_spaces_visible",
    }


# The sign-in checks of each source with named checks. A pass of one unlocks
# the create form, whether or not the source has credential-bound fields.
_SIGN_IN_CHECK_IDS: dict[DocumentSource, frozenset[str]] = {
    DocumentSource.ASANA: frozenset({"asana_token"}),
    DocumentSource.CONFLUENCE: frozenset(
        {"confluence_auth", "confluence_scoped_token_auth"}
    ),
    DocumentSource.GITHUB: frozenset({"github_auth"}),
    DocumentSource.GOOGLE_DRIVE: frozenset({"google_drive_auth"}),
    DocumentSource.HUBSPOT: frozenset({"hubspot_token"}),
    DocumentSource.JIRA: frozenset({"jira_auth", "jira_scoped_token_auth"}),
    DocumentSource.LINEAR: frozenset({"linear_token"}),
    DocumentSource.NOTION: frozenset({"notion_auth"}),
    DocumentSource.ONEDRIVE: frozenset({"onedrive_token_auth"}),
    DocumentSource.OUTLOOK: frozenset({"outlook_token_auth"}),
    DocumentSource.SHAREPOINT: frozenset({"sharepoint_token_auth"}),
    DocumentSource.SLACK: frozenset({"slack_token_auth"}),
    DocumentSource.YOUTRACK: frozenset({"youtrack_token"}),
    DocumentSource.AZURE_DATALAKE: frozenset({"adls_sign_in"}),
}


def test_every_source_with_named_checks_names_its_sign_in_checks() -> None:
    named: set[DocumentSource] = {
        source
        for source in DocumentSource
        if any(not check.is_fallback for check in get_capability_checks(source))
    }
    assert named == set(_SIGN_IN_CHECK_IDS)


@pytest.mark.parametrize("source", sorted(_SIGN_IN_CHECK_IDS, key=str))
def test_the_sign_in_check_unlocks_the_form(source: DocumentSource) -> None:
    checks: list[CapabilityCheck[Any]] = get_capability_checks(source)
    sign_in: frozenset[str] = _SIGN_IN_CHECK_IDS[source]
    unlocking: set[str] = {
        check.check_id for check in checks if check.validates_binding
    }
    assert sign_in <= unlocking
    # Another unlocking check (e.g. "List users") runs after one that unlocks.
    for check in checks:
        if check.check_id in unlocking - sign_in:
            assert set(check.depends_on) & unlocking, check.check_id
            assert not check.discovery, check.check_id
