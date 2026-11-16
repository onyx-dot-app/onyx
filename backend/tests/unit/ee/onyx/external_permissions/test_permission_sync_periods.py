"""How often a pair's permission syncs run now, before the Cloud multiplier. The
schedulers and fleet telemetry both read these."""

from ee.onyx.configs.app_configs import (
    CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY,
    DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY,
    GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY,
    SLACK_PERMISSION_DOC_SYNC_FREQUENCY,
)
from ee.onyx.external_permissions.sync_params import (
    doc_permission_sync_seconds,
    external_group_sync_seconds,
)
from onyx.configs.constants import DocumentSource
from onyx.db.enums import ConnectorCredentialPairStatus

_ACTIVE: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE
_INDEXING: tuple[ConnectorCredentialPairStatus, ...] = (
    ConnectorCredentialPairStatus.SCHEDULED,
    ConnectorCredentialPairStatus.INITIAL_INDEXING,
)
_STOPPED: tuple[ConnectorCredentialPairStatus, ...] = (
    ConnectorCredentialPairStatus.PAUSED,
    ConnectorCredentialPairStatus.INVALID,
    ConnectorCredentialPairStatus.DELETING,
)


def test_periods_follow_each_source_sync_config() -> None:
    drive: DocumentSource = DocumentSource.GOOGLE_DRIVE
    assert (
        doc_permission_sync_seconds(drive, _ACTIVE, indexed=True)
        == DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY
    )
    assert (
        external_group_sync_seconds(drive, _ACTIVE)
        == GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY
    )
    # Slack has no group sync, and the web connector no permission sync at all.
    assert (
        doc_permission_sync_seconds(DocumentSource.SLACK, _ACTIVE, indexed=True)
        == SLACK_PERMISSION_DOC_SYNC_FREQUENCY
    )
    assert external_group_sync_seconds(DocumentSource.SLACK, _ACTIVE) is None
    assert (
        doc_permission_sync_seconds(DocumentSource.WEB, _ACTIVE, indexed=True) is None
    )
    assert external_group_sync_seconds(DocumentSource.WEB, _ACTIVE) is None


def test_a_doc_sync_runs_only_for_an_active_pair_after_its_first_index() -> None:
    drive: DocumentSource = DocumentSource.GOOGLE_DRIVE
    for status in (*_INDEXING, *_STOPPED):
        assert doc_permission_sync_seconds(drive, status, indexed=True) is None
    # Google Drive's indexing also syncs permissions, so its doc sync waits.
    assert doc_permission_sync_seconds(drive, _ACTIVE, indexed=False) is None


def test_a_group_sync_also_runs_while_a_pair_indexes() -> None:
    for status in _INDEXING:
        assert (
            external_group_sync_seconds(DocumentSource.CONFLUENCE, status)
            == CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY
        )
    for status in _STOPPED:
        assert external_group_sync_seconds(DocumentSource.CONFLUENCE, status) is None
