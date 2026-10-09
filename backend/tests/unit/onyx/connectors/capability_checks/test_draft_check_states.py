"""Draft states from the readiness decision, and draft result cache keys."""

from datetime import datetime, timezone
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckState,
    DraftCheckStateKind,
    decide_draft_check_state,
    draft_result_cache_key,
)
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.db.enums import AccessType


class _SlackCheck(CapabilityCheck[SlackConnectorConfig]):
    config_class = SlackConnectorConfig

    def __init__(
        self,
        *,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        requires_fields: frozenset[str] = frozenset(),
        requires_connector_config: bool = False,
        requires_connector_instance: bool = False,
        applies_to_regex: bool = True,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id="test_check",
            display_name="Test check",
            requires_connector_instance=requires_connector_instance,
            requires_connector_config=requires_connector_config,
            requires_fields=requires_fields,
        )
        self._applies_to_regex = applies_to_regex

    def applies(self, form_state: FormState[SlackConnectorConfig]) -> bool:
        return self._applies_to_regex or not form_state.config.channel_regex_enabled

    def run(self, context: CapabilityCheckContext) -> None:
        pass


def _state(
    check: _SlackCheck,
    config: dict[str, Any] | None,
    access_type: AccessType | None = None,
) -> DraftCheckState:
    return decide_draft_check_state(
        check,
        CapabilityCheckContext(
            source=DocumentSource.SLACK,
            credential_json={},
            connector_specific_config=config,
            access_type=access_type,
        ),
    )


def test_missing_required_field_waits_and_names_it() -> None:
    state = _state(_SlackCheck(requires_fields=frozenset({"channels"})), {})

    assert state.state == DraftCheckStateKind.WAITING
    assert state.missing_fields == ["channels"]


def test_invalid_field_waits_instead_of_failing() -> None:
    state = _state(
        _SlackCheck(requires_connector_config=True),
        {"channels": ["eng"], "batch_size": "x"},
    )

    assert state.state == DraftCheckStateKind.WAITING
    assert state.invalid_fields == ["batch_size"]


def test_config_less_form_makes_a_config_reading_check_wait() -> None:
    state = _state(_SlackCheck(requires_connector_config=True), None)

    assert state.state == DraftCheckStateKind.WAITING


@pytest.mark.parametrize(
    "access_type,expected",
    [
        (AccessType.SYNC, DraftCheckStateKind.PENDING),
        (AccessType.PUBLIC, DraftCheckStateKind.NOT_APPLICABLE),
    ],
)
def test_access_type_decides_applicability(
    access_type: AccessType, expected: DraftCheckStateKind
) -> None:
    check = _SlackCheck(capability=CredentialCapability.DOC_PERMISSION_SYNC)

    assert _state(check, None, access_type).state == expected


def test_applies_false_is_not_applicable() -> None:
    check = _SlackCheck(requires_connector_config=True, applies_to_regex=False)

    state = _state(check, {"channel_regex_enabled": True})

    assert state.state == DraftCheckStateKind.NOT_APPLICABLE


def test_instance_check_runs_only_on_a_complete_config() -> None:
    check = _SlackCheck(requires_connector_instance=True)

    assert _state(check, None).state == DraftCheckStateKind.WAITING
    assert _state(check, {"channels": ["eng"]}).state == DraftCheckStateKind.PENDING


class _CredentialOnlyCheck(CapabilityCheck):
    """Reads no config itself; only the source's gateway may."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="test_credential_check",
            display_name="Credential check",
            requires_connector_instance=False,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        pass


def _key(
    check: CapabilityCheck[Any],
    form_values: dict[str, Any] | None,
    source: DocumentSource = DocumentSource.SLACK,
) -> str:
    return draft_result_cache_key(
        credential_id=1,
        credential_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source=source,
        access_type=AccessType.PUBLIC,
        check=check,
        form_values=form_values,
    )


def test_cache_key_ignores_form_edits_for_config_independent_checks() -> None:
    check = _CredentialOnlyCheck()

    assert _key(check, {"channels": ["eng"]}) == _key(check, {"channels": ["ops"]})
    assert _key(check, {"channels": ["eng"]}) == _key(check, None)


@pytest.mark.parametrize("source", [DocumentSource.OUTLOOK, DocumentSource.ONEDRIVE])
def test_cache_key_follows_the_hosts_that_the_gateway_reads(
    source: DocumentSource,
) -> None:
    check = _CredentialOnlyCheck()
    default = {"authority_host": "", "users": ["a@contoso.com"]}

    assert _key(check, default, source) == _key(check, None, source)
    assert _key(check, {**default, "users": ["b@contoso.com"]}, source) == _key(
        check, default, source
    )
    assert _key(
        check, {**default, "authority_host": "https://login.microsoftonline.us"}, source
    ) != _key(check, default, source)
    assert _key(
        check, {**default, "graph_api_host": "https://graph.microsoft.us"}, source
    ) != _key(check, default, source)


def test_cache_key_follows_the_form_for_a_check_with_a_config_class() -> None:
    check = _SlackCheck()

    assert _key(check, {"channels": ["eng"]}) != _key(check, {"channels": ["ops"]})


def test_cache_key_follows_form_edits_for_config_reading_checks() -> None:
    check = _SlackCheck(requires_connector_config=True)

    assert _key(check, {"channels": ["eng"]}) != _key(check, {"channels": ["ops"]})
    assert _key(check, {"channels": ["eng"]}) == _key(check, {"channels": ["eng"]})
