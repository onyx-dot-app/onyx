from collections.abc import Generator
from typing import Any
from typing import Final

from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsFunction
from ee.onyx.external_permissions.perm_sync_types import FetchAllDocumentsIdsFunction
from ee.onyx.external_permissions.utils import generic_doc_sync
from onyx.access.models import ElementExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Label used to tag log messages and metrics emitted by this sync function.
JSM_DOC_SYNC_TAG: Final[str] = "jira_service_management_doc_sync"


def _validate_jsm_config(connector_specific_config: dict[str, Any]) -> None:
    """Validate that required JSM connector fields are present and well-formed.

    Raises:
        ConnectorValidationError: If ``jira_base_url`` is absent or is not a
            non-empty string that starts with ``http://`` or ``https://``.
            This prevents silent permission-sync failures caused by a
            misconfigured connector storing documents under wrong IDs.
    """
    jira_base_url = connector_specific_config.get("jira_base_url", "")
    if not isinstance(jira_base_url, str) or not jira_base_url.strip():
        raise ConnectorValidationError(
            "JSM permission sync requires a non-empty 'jira_base_url' in the "
            "connector configuration.  Please re-save the connector with a "
            "valid Jira base URL."
        )
    normalized = jira_base_url.strip().lower()
    if not (normalized.startswith("http://") or normalized.startswith("https://")):
        raise ConnectorValidationError(
            f"'jira_base_url' must begin with 'http://' or 'https://', "
            f"got: {jira_base_url!r}.  Please correct the connector "
            f"configuration and try again."
        )


def jira_service_management_doc_sync(
    cc_pair: ConnectorCredentialPair,
    fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
    fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
    callback: IndexingHeartbeatInterface | None = None,
) -> Generator[ElementExternalAccess, None, None]:
    """Sync external permissions for Jira Service Management documents.

    Validates the connector configuration before constructing the JSM
    connector to provide actionable error messages on misconfiguration
    rather than cryptic failures deep in the permission-sync pipeline.

    Args:
        cc_pair: The connector-credential pair for this sync run.
        fetch_all_existing_docs_fn: Callable that returns all known documents
            for this connector.  Required by the ``DocSyncFuncType`` protocol
            but not consumed on the JSM path -- ``generic_doc_sync`` uses
            ``fetch_all_existing_docs_ids_fn`` instead.
        fetch_all_existing_docs_ids_fn: Callable that returns all known
            document IDs for this connector; used by ``generic_doc_sync`` to
            detect stale documents.
        callback: Optional heartbeat interface for long-running sync jobs.
    """
    connector_specific_config: dict[str, Any] = (
        cc_pair.connector.connector_specific_config
    )

    # Validate URL before any network calls so that a bad config surfaces a
    # clear error instead of silently producing wrong document IDs.
    _validate_jsm_config(connector_specific_config)

    jsm_connector = JiraServiceManagementConnector(
        jira_base_url=connector_specific_config.get("jira_base_url", ""),
        project_key=connector_specific_config.get("project_key"),
        comment_email_blacklist=connector_specific_config.get("comment_email_blacklist"),
        jql_query=connector_specific_config.get("jql_query"),
        scoped_token=connector_specific_config.get("scoped_token", False),
    )
    credential_json = (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
    jsm_connector.load_credentials(credential_json)
    yield from generic_doc_sync(
        cc_pair=cc_pair,
        fetch_all_existing_docs_ids_fn=fetch_all_existing_docs_ids_fn,
        callback=callback,
        doc_source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        slim_connector=jsm_connector,
        label=JSM_DOC_SYNC_TAG,
    )
