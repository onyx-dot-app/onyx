from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from ee.onyx.configs.app_configs import (
    BOX_PERMISSION_DOC_SYNC_FREQUENCY,
    BOX_PERMISSION_GROUP_SYNC_FREQUENCY,
    CANVAS_PERMISSION_DOC_SYNC_FREQUENCY,
    CANVAS_PERMISSION_GROUP_SYNC_FREQUENCY,
    CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY,
    CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY,
    DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY,
    GITHUB_PERMISSION_DOC_SYNC_FREQUENCY,
    GITHUB_PERMISSION_GROUP_SYNC_FREQUENCY,
    GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY,
    JIRA_PERMISSION_DOC_SYNC_FREQUENCY,
    JIRA_PERMISSION_GROUP_SYNC_FREQUENCY,
    SHAREPOINT_PERMISSION_DOC_SYNC_FREQUENCY,
    SHAREPOINT_PERMISSION_GROUP_SYNC_FREQUENCY,
    SLACK_PERMISSION_DOC_SYNC_FREQUENCY,
    TEAMS_PERMISSION_DOC_SYNC_FREQUENCY,
)
from ee.onyx.external_permissions.perm_sync_types import (
    CensoringFuncType,
    DocSyncFuncType,
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
    GroupSyncFuncType,
)
from onyx.configs.constants import DocumentSource

if TYPE_CHECKING:
    from ee.onyx.db.external_perm import ExternalUserGroup  # noqa
    from onyx.access.models import DocExternalAccess, ElementExternalAccess  # noqa
    from onyx.context.search.models import InferenceChunk  # noqa
    from onyx.db.models import ConnectorCredentialPair  # noqa
    from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface  # noqa


# Sync implementations import their connector SDKs (box_sdk_gen, office365,
# google, github, ...), which cost ~60 MB. Load them on first call so workers
# that only read this config stay small.
def _lazy_doc_sync(load: Callable[[], DocSyncFuncType]) -> DocSyncFuncType:
    def run(
        cc_pair: "ConnectorCredentialPair",
        fetch_all_docs_fn: FetchAllDocumentsFunction,
        fetch_all_docs_ids_fn: FetchAllDocumentsIdsFunction,
        callback: Optional["IndexingHeartbeatInterface"],
    ) -> Generator["ElementExternalAccess", None, None]:
        return load()(cc_pair, fetch_all_docs_fn, fetch_all_docs_ids_fn, callback)

    return run


def _lazy_group_sync(load: Callable[[], GroupSyncFuncType]) -> GroupSyncFuncType:
    def run(
        tenant_id: str, cc_pair: "ConnectorCredentialPair"
    ) -> Generator["ExternalUserGroup", None, None]:
        return load()(tenant_id, cc_pair)

    return run


def _lazy_censoring(load: Callable[[], CensoringFuncType]) -> CensoringFuncType:
    def run(chunks: list["InferenceChunk"], user_email: str) -> list["InferenceChunk"]:
        return load()(chunks, user_email)

    return run


def _load_box_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.box.doc_sync import box_doc_sync

    return box_doc_sync


def _load_box_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.box.group_sync import box_group_sync

    return box_group_sync


def _load_canvas_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.canvas.doc_sync import canvas_doc_sync

    return canvas_doc_sync


def _load_canvas_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.canvas.group_sync import canvas_group_sync

    return canvas_group_sync


def _load_confluence_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.confluence.doc_sync import confluence_doc_sync

    return confluence_doc_sync


def _load_confluence_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.confluence.group_sync import confluence_group_sync

    return confluence_group_sync


def _load_github_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.github.doc_sync import github_doc_sync

    return github_doc_sync


def _load_github_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.github.group_sync import github_group_sync

    return github_group_sync


def _load_gmail_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.gmail.doc_sync import gmail_doc_sync

    return gmail_doc_sync


def _load_gdrive_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.google_drive.doc_sync import gdrive_doc_sync

    return gdrive_doc_sync


def _load_gdrive_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.google_drive.group_sync import gdrive_group_sync

    return gdrive_group_sync


def _load_jira_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.jira.doc_sync import jira_doc_sync

    return jira_doc_sync


def _load_jira_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.jira.group_sync import jira_group_sync

    return jira_group_sync


def _load_jira_service_management_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.jira.doc_sync import (
        jira_service_management_doc_sync,
    )

    return jira_service_management_doc_sync


def _load_censor_salesforce_chunks() -> CensoringFuncType:
    from ee.onyx.external_permissions.salesforce.postprocessing import (
        censor_salesforce_chunks,
    )

    return censor_salesforce_chunks


def _load_sharepoint_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.sharepoint.doc_sync import sharepoint_doc_sync

    return sharepoint_doc_sync


def _load_sharepoint_group_sync() -> GroupSyncFuncType:
    from ee.onyx.external_permissions.sharepoint.group_sync import sharepoint_group_sync

    return sharepoint_group_sync


def _load_slack_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.slack.doc_sync import slack_doc_sync

    return slack_doc_sync


def _load_teams_doc_sync() -> DocSyncFuncType:
    from ee.onyx.external_permissions.teams.doc_sync import teams_doc_sync

    return teams_doc_sync


class DocSyncConfig(BaseModel):
    doc_sync_frequency: int
    doc_sync_func: DocSyncFuncType
    initial_index_should_sync: bool


class GroupSyncConfig(BaseModel):
    group_sync_frequency: int
    group_sync_func: GroupSyncFuncType
    group_sync_is_cc_pair_agnostic: bool


class CensoringConfig(BaseModel):
    chunk_censoring_func: CensoringFuncType


class SyncConfig(BaseModel):
    # None means we don't perform a doc_sync
    doc_sync_config: DocSyncConfig | None = None
    # None means we don't perform a group_sync
    group_sync_config: GroupSyncConfig | None = None
    # None means we don't perform a chunk_censoring
    censoring_config: CensoringConfig | None = None


# Mock doc sync function for testing (no-op)
def mock_doc_sync(
    cc_pair: "ConnectorCredentialPair",  # noqa: ARG001
    fetch_all_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG001
    callback: Optional["IndexingHeartbeatInterface"],  # noqa: ARG001
) -> Generator["DocExternalAccess", None, None]:
    """Mock doc sync function for testing - returns empty list since permissions are fetched during indexing"""
    yield from []


_SOURCE_TO_SYNC_CONFIG: dict[DocumentSource, SyncConfig] = {
    DocumentSource.GOOGLE_DRIVE: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_gdrive_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_gdrive_group_sync),
            group_sync_is_cc_pair_agnostic=False,
        ),
    ),
    DocumentSource.CONFLUENCE: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_confluence_doc_sync),
            initial_index_should_sync=False,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_confluence_group_sync),
            group_sync_is_cc_pair_agnostic=True,
        ),
    ),
    DocumentSource.JIRA: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=JIRA_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_jira_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=JIRA_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_jira_group_sync),
            group_sync_is_cc_pair_agnostic=True,
        ),
    ),
    DocumentSource.JIRA_SERVICE_MANAGEMENT: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=JIRA_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_jira_service_management_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=JIRA_PERMISSION_GROUP_SYNC_FREQUENCY,
            # Service desk requests live in the same Jira instance, so the groups
            # come from the same endpoint.
            group_sync_func=_lazy_group_sync(_load_jira_group_sync),
            group_sync_is_cc_pair_agnostic=True,
        ),
    ),
    DocumentSource.CANVAS: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=CANVAS_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_canvas_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=CANVAS_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_canvas_group_sync),
            group_sync_is_cc_pair_agnostic=False,
        ),
    ),
    DocumentSource.BOX: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=BOX_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_box_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=BOX_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_box_group_sync),
            group_sync_is_cc_pair_agnostic=False,
        ),
    ),
    # Groups are not needed for Slack.
    # All channel access is done at the individual user level.
    DocumentSource.SLACK: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=SLACK_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_slack_doc_sync),
            initial_index_should_sync=True,
        ),
    ),
    DocumentSource.GMAIL: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_gmail_doc_sync),
            initial_index_should_sync=False,
        ),
    ),
    DocumentSource.GITHUB: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=GITHUB_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_github_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=GITHUB_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_github_group_sync),
            group_sync_is_cc_pair_agnostic=False,
        ),
    ),
    DocumentSource.SALESFORCE: SyncConfig(
        censoring_config=CensoringConfig(
            chunk_censoring_func=_lazy_censoring(_load_censor_salesforce_chunks),
        ),
    ),
    DocumentSource.MOCK_CONNECTOR: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=mock_doc_sync,
            initial_index_should_sync=True,
        ),
    ),
    # Groups are not needed for Teams.
    # All channel access is done at the individual user level.
    DocumentSource.TEAMS: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=TEAMS_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_teams_doc_sync),
            initial_index_should_sync=True,
        ),
    ),
    DocumentSource.SHAREPOINT: SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=SHAREPOINT_PERMISSION_DOC_SYNC_FREQUENCY,
            doc_sync_func=_lazy_doc_sync(_load_sharepoint_doc_sync),
            initial_index_should_sync=True,
        ),
        group_sync_config=GroupSyncConfig(
            group_sync_frequency=SHAREPOINT_PERMISSION_GROUP_SYNC_FREQUENCY,
            group_sync_func=_lazy_group_sync(_load_sharepoint_group_sync),
            group_sync_is_cc_pair_agnostic=False,
        ),
    ),
}


def source_requires_doc_sync(source: DocumentSource) -> bool:
    """Checks if the given DocumentSource requires doc syncing."""
    if source not in _SOURCE_TO_SYNC_CONFIG:
        return False
    return _SOURCE_TO_SYNC_CONFIG[source].doc_sync_config is not None


def source_requires_external_group_sync(source: DocumentSource) -> bool:
    """Checks if the given DocumentSource requires external group syncing."""
    if source not in _SOURCE_TO_SYNC_CONFIG:
        return False
    return _SOURCE_TO_SYNC_CONFIG[source].group_sync_config is not None


def get_source_perm_sync_config(source: DocumentSource) -> SyncConfig | None:
    """Returns the frequency of the external group sync for the given DocumentSource."""
    return _SOURCE_TO_SYNC_CONFIG.get(source)


def source_group_sync_is_cc_pair_agnostic(source: DocumentSource) -> bool:
    """Checks if the given DocumentSource requires external group syncing."""
    if source not in _SOURCE_TO_SYNC_CONFIG:
        return False

    group_sync_config = _SOURCE_TO_SYNC_CONFIG[source].group_sync_config
    if group_sync_config is None:
        return False

    return group_sync_config.group_sync_is_cc_pair_agnostic


def get_all_cc_pair_agnostic_group_sync_sources() -> set[DocumentSource]:
    """Returns the set of sources that have external group syncing that is cc_pair agnostic."""
    return {
        source
        for source, sync_config in _SOURCE_TO_SYNC_CONFIG.items()
        if sync_config.group_sync_config is not None
        and sync_config.group_sync_config.group_sync_is_cc_pair_agnostic
    }


def check_if_valid_sync_source(source_type: DocumentSource) -> bool:
    return source_type in _SOURCE_TO_SYNC_CONFIG


def get_all_censoring_enabled_sources() -> set[DocumentSource]:
    """Returns the set of sources that have censoring enabled."""
    return {
        source
        for source, sync_config in _SOURCE_TO_SYNC_CONFIG.items()
        if sync_config.censoring_config is not None
    }


def source_should_fetch_permissions_during_indexing(source: DocumentSource) -> bool:
    """Returns True if the given DocumentSource requires permissions to be fetched during indexing."""
    if source not in _SOURCE_TO_SYNC_CONFIG:
        return False

    doc_sync_config = _SOURCE_TO_SYNC_CONFIG[source].doc_sync_config
    if doc_sync_config is None:
        return False

    return doc_sync_config.initial_index_should_sync
