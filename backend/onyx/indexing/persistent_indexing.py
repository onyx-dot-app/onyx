"""Helpers for the PERSISTENT_INDEXING catch-all error path.

These are used by the docfetching / docprocessing task entrypoints to convert
unanticipated exceptions into ConnectorFailure records so the index attempt
can finish as COMPLETED_WITH_ERRORS instead of FAILED. Use only as a
last-resort catch-all; connectors should keep yielding their own targeted
ConnectorFailure objects with proper context for known error conditions.
"""

import sentry_sdk

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.index_attempt import create_index_attempt_error
from onyx.utils.logger import setup_logger

logger = setup_logger()


GENERIC_FAILURE_SENTRY_FINGERPRINT_PREFIX = "persistent-indexing-generic-failure"


def build_generic_connector_failure(
    *,
    exc: BaseException,
    document: Document | None = None,
    entity_id: str | None = None,
) -> ConnectorFailure:
    """Build a ConnectorFailure for an unanticipated exception in the indexing
    pipeline. Exactly one of `document` or `entity_id` must be provided:
    `DocumentFailure` when the doc id is known, otherwise `EntityFailure`."""
    if (document is None) == (entity_id is None):
        raise ValueError(
            "build_generic_connector_failure requires exactly one of "
            "`document` or `entity_id`"
        )

    if document is not None:
        document_link: str | None = None
        if document.sections:
            document_link = document.sections[0].link
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=document.id,
                document_link=document_link,
            ),
            failure_message=str(exc),
            exception=exc if isinstance(exc, Exception) else None,
        )

    assert entity_id is not None  # linter
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=entity_id),
        failure_message=str(exc),
        exception=exc if isinstance(exc, Exception) else None,
    )


def record_generic_failure(
    index_attempt_id: int,
    cc_pair_id: int,
    source: DocumentSource,
    tenant_id: str,
    failure: ConnectorFailure,
) -> None:
    """Tag Sentry, then persist the failure via `create_index_attempt_error`.

    Swallows DB errors with `logger.exception` so the recovery path itself
    can't kill the attempt."""
    exc = failure.exception
    if exc is not None:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("stage", "persistent_indexing_catch_all")
            scope.set_tag("connector_source", source.value)
            scope.set_tag("cc_pair_id", str(cc_pair_id))
            scope.set_tag("index_attempt_id", str(index_attempt_id))
            scope.set_tag("tenant_id", tenant_id)
            if failure.failed_document:
                scope.set_tag("doc_id", failure.failed_document.document_id)
            if failure.failed_entity:
                scope.set_tag("entity_id", failure.failed_entity.entity_id)
            scope.fingerprint = [
                GENERIC_FAILURE_SENTRY_FINGERPRINT_PREFIX,
                source.value,
                type(exc).__name__,
            ]
            sentry_sdk.capture_exception(exc)

    try:
        with get_session_with_current_tenant() as db_session:
            create_index_attempt_error(
                index_attempt_id,
                cc_pair_id,
                failure,
                db_session,
            )
    except Exception:
        # Recording failure must never itself kill the attempt; if the DB write
        # fails we still want the task to return cleanly under PERSISTENT_INDEXING.
        logger.exception(
            "Failed to persist generic indexing failure: attempt=%s cc_pair=%s",
            index_attempt_id,
            cc_pair_id,
        )
