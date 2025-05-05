from ee.onyx.configs.app_configs import CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY
from ee.onyx.configs.app_configs import CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY
from ee.onyx.configs.app_configs import GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY
from ee.onyx.configs.app_configs import SLACK_PERMISSION_DOC_SYNC_FREQUENCY
from ee.onyx.external_permissions.confluence.doc_sync import confluence_doc_sync
from ee.onyx.external_permissions.confluence.group_sync import confluence_group_sync
from ee.onyx.external_permissions.gmail.doc_sync import gmail_doc_sync
from ee.onyx.external_permissions.google_drive.doc_sync import gdrive_doc_sync
from ee.onyx.external_permissions.google_drive.group_sync import gdrive_group_sync
from ee.onyx.external_permissions.perm_sync_types import DocSyncFuncType
from ee.onyx.external_permissions.perm_sync_types import GroupSyncFuncType
from ee.onyx.external_permissions.post_query_censoring import (
    DOC_SOURCE_TO_CHUNK_CENSORING_FUNCTION,
)
from ee.onyx.external_permissions.slack.doc_sync import slack_doc_sync
from ee.onyx.external_permissions.slack.group_sync import slack_group_sync
from onyx.configs.constants import DocumentSource


# These functions update:
# - the user_email <-> document mapping
# - the external_user_group_id <-> document mapping
# in postgres without committing
# THIS ONE IS NECESSARY FOR AUTO SYNC TO WORK
DOC_PERMISSIONS_FUNC_MAP: dict[DocumentSource, DocSyncFuncType] = {
    DocumentSource.GOOGLE_DRIVE: gdrive_doc_sync,
    DocumentSource.CONFLUENCE: confluence_doc_sync,
    DocumentSource.SLACK: slack_doc_sync,
    DocumentSource.GMAIL: gmail_doc_sync,
}


def source_requires_doc_sync(source: DocumentSource) -> bool:
    """Checks if the given DocumentSource requires doc syncing."""
    return source in DOC_PERMISSIONS_FUNC_MAP


# These functions update:
# - the user_email <-> external_user_group_id mapping
# in postgres without committing
# THIS ONE IS OPTIONAL ON AN APP BY APP BASIS
GROUP_PERMISSIONS_FUNC_MAP: dict[DocumentSource, GroupSyncFuncType] = {
    DocumentSource.GOOGLE_DRIVE: gdrive_group_sync,
    DocumentSource.CONFLUENCE: confluence_group_sync,
    DocumentSource.SLACK: slack_group_sync,
}


def source_requires_external_group_sync(source: DocumentSource) -> bool:
    """Checks if the given DocumentSource requires external group syncing."""
    return source in GROUP_PERMISSIONS_FUNC_MAP


GROUP_PERMISSIONS_IS_CC_PAIR_AGNOSTIC: set[DocumentSource] = {
    DocumentSource.CONFLUENCE,
}


def source_group_sync_is_cc_pair_agnostic(source: DocumentSource) -> bool:
    """Checks if the given DocumentSource requires external group syncing."""
    return source in GROUP_PERMISSIONS_IS_CC_PAIR_AGNOSTIC


# If nothing is specified here, we run the doc_sync every time the celery beat runs
DOC_PERMISSION_SYNC_PERIODS: dict[DocumentSource, int] = {
    # Polling is not supported so we fetch all doc permissions every 5 minutes
    DocumentSource.CONFLUENCE: CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY,
    DocumentSource.SLACK: SLACK_PERMISSION_DOC_SYNC_FREQUENCY,
}

# If nothing is specified here, we run the doc_sync every time the celery beat runs
EXTERNAL_GROUP_SYNC_PERIODS: dict[DocumentSource, int] = {
    # Polling is not supported so we fetch all group permissions every 30 minutes
    DocumentSource.GOOGLE_DRIVE: GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY,
    DocumentSource.CONFLUENCE: CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY,
}


def check_if_valid_sync_source(source_type: DocumentSource) -> bool:
    return (
        source_type in DOC_PERMISSIONS_FUNC_MAP
        or source_type in DOC_SOURCE_TO_CHUNK_CENSORING_FUNCTION
    )
