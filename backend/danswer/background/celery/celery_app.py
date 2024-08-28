import json
from datetime import timedelta
from typing import Any
from typing import cast

from celery import Celery  # type: ignore
from celery.contrib.abortable import AbortableTask  # type: ignore
from celery.exceptions import TaskRevokedError
from sqlalchemy import text
from sqlalchemy.orm import Session

from danswer.background.celery.celery_utils import extract_ids_from_runnable_connector
from danswer.background.celery.celery_utils import should_kick_off_deletion_of_cc_pair
from danswer.background.celery.celery_utils import should_prune_cc_pair
from danswer.background.celery.celery_utils import should_sync_doc_set
from danswer.background.connector_deletion import delete_connector_credential_pair
from danswer.background.connector_deletion import delete_connector_credential_pair_batch
from danswer.background.task_utils import build_celery_task_wrapper
from danswer.background.task_utils import name_cc_cleanup_task
from danswer.background.task_utils import name_cc_prune_task
from danswer.background.task_utils import name_document_set_sync_task
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.configs.constants import POSTGRES_CELERY_APP_NAME
from danswer.configs.constants import PostgresAdvisoryLocks
from danswer.connectors.factory import instantiate_connector
from danswer.connectors.models import InputType
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.deletion_attempt import check_deletion_attempt_is_allowed
from danswer.db.document import get_documents_for_connector_credential_pair
from danswer.db.document import prepare_to_modify_documents
from danswer.db.document_set import delete_document_set
from danswer.db.document_set import fetch_document_sets
from danswer.db.document_set import fetch_document_sets_for_documents
from danswer.db.document_set import fetch_documents_for_document_set_paginated
from danswer.db.document_set import get_document_set_by_id
from danswer.db.document_set import mark_document_set_as_synced
from danswer.db.engine import build_connection_string
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.engine import SYNC_DB_API
from danswer.db.models import DocumentSet
from danswer.document_index.document_index_utils import get_both_index_names
from danswer.document_index.factory import get_default_document_index
from danswer.document_index.interfaces import UpdateRequest
from danswer.utils.logger import setup_logger

logger = setup_logger()

connection_string = build_connection_string(
    db_api=SYNC_DB_API, app_name=POSTGRES_CELERY_APP_NAME
)
celery_broker_url = f"sqla+{connection_string}"
celery_backend_url = f"db+{connection_string}"
celery_app = Celery(__name__, broker=celery_broker_url, backend=celery_backend_url)


_SYNC_BATCH_SIZE = 100


#####
# Tasks that need to be run in job queue, registered via APIs
#
# If imports from this module are needed, use local imports to avoid circular importing
#####
@build_celery_task_wrapper(name_cc_cleanup_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def cleanup_connector_credential_pair_task(
    connector_id: int,
    credential_id: int,
) -> int:
    """Connector deletion task. This is run as an async task because it is a somewhat slow job.
    Needs to potentially update a large number of Postgres and Vespa docs, including deleting them
    or updating the ACL"""
    engine = get_sqlalchemy_engine()
    with Session(engine) as db_session:
        # validate that the connector / credential pair is deletable
        cc_pair = get_connector_credential_pair(
            db_session=db_session,
            connector_id=connector_id,
            credential_id=credential_id,
        )
        if not cc_pair:
            raise ValueError(
                f"Cannot run deletion attempt - connector_credential_pair with Connector ID: "
                f"{connector_id} and Credential ID: {credential_id} does not exist."
            )

        deletion_attempt_disallowed_reason = check_deletion_attempt_is_allowed(
            connector_credential_pair=cc_pair, db_session=db_session
        )
        if deletion_attempt_disallowed_reason:
            raise ValueError(deletion_attempt_disallowed_reason)

        try:
            # The bulk of the work is in here, updates Postgres and Vespa
            curr_ind_name, sec_ind_name = get_both_index_names(db_session)
            document_index = get_default_document_index(
                primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
            )
            return delete_connector_credential_pair(
                db_session=db_session,
                document_index=document_index,
                cc_pair=cc_pair,
            )
        except Exception as e:
            logger.exception(f"Failed to run connector_deletion due to {e}")
            raise e


@build_celery_task_wrapper(name_cc_prune_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def prune_documents_task(connector_id: int, credential_id: int) -> None:
    """connector pruning task. For a cc pair, this task pulls all document IDs from the source
    and compares those IDs to locally stored documents and deletes all locally stored IDs missing
    from the most recently pulled document ID list"""
    with Session(get_sqlalchemy_engine()) as db_session:
        try:
            cc_pair = get_connector_credential_pair(
                db_session=db_session,
                connector_id=connector_id,
                credential_id=credential_id,
            )

            if not cc_pair:
                logger.warning(f"ccpair not found for {connector_id} {credential_id}")
                return

            runnable_connector = instantiate_connector(
                cc_pair.connector.source,
                InputType.PRUNE,
                cc_pair.connector.connector_specific_config,
                cc_pair.credential,
                db_session,
            )

            all_connector_doc_ids: set[str] = extract_ids_from_runnable_connector(
                runnable_connector
            )

            all_indexed_document_ids = {
                doc.id
                for doc in get_documents_for_connector_credential_pair(
                    db_session=db_session,
                    connector_id=connector_id,
                    credential_id=credential_id,
                )
            }

            doc_ids_to_remove = list(all_indexed_document_ids - all_connector_doc_ids)

            curr_ind_name, sec_ind_name = get_both_index_names(db_session)
            document_index = get_default_document_index(
                primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
            )

            if len(doc_ids_to_remove) == 0:
                logger.info(
                    f"No docs to prune from {cc_pair.connector.source} connector"
                )
                return

            logger.info(
                f"pruning {len(doc_ids_to_remove)} doc(s) from {cc_pair.connector.source} connector"
            )
            delete_connector_credential_pair_batch(
                document_ids=doc_ids_to_remove,
                connector_id=connector_id,
                credential_id=credential_id,
                document_index=document_index,
            )
        except Exception as e:
            logger.exception(
                f"Failed to run pruning for connector id {connector_id} due to {e}"
            )
            raise e


@build_celery_task_wrapper(name_document_set_sync_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_document_set_task(document_set_id: int) -> None:
    """For document sets marked as not up to date, sync the state from postgres
    into the datastore. Also handles deletions."""

    def _sync_document_batch(document_ids: list[str], db_session: Session) -> None:
        logger.debug(f"Syncing document sets for: {document_ids}")

        # Acquires a lock on the documents so that no other process can modify them
        with prepare_to_modify_documents(
            db_session=db_session, document_ids=document_ids
        ):
            # get current state of document sets for these documents
            document_set_map = {
                document_id: document_sets
                for document_id, document_sets in fetch_document_sets_for_documents(
                    document_ids=document_ids, db_session=db_session
                )
            }

            # update Vespa
            curr_ind_name, sec_ind_name = get_both_index_names(db_session)
            document_index = get_default_document_index(
                primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
            )
            update_requests = [
                UpdateRequest(
                    document_ids=[document_id],
                    document_sets=set(document_set_map.get(document_id, [])),
                )
                for document_id in document_ids
            ]
            document_index.update(update_requests=update_requests)

    with Session(get_sqlalchemy_engine()) as db_session:
        try:
            cursor = None
            while True:
                document_batch, cursor = fetch_documents_for_document_set_paginated(
                    document_set_id=document_set_id,
                    db_session=db_session,
                    current_only=False,
                    last_document_id=cursor,
                    limit=_SYNC_BATCH_SIZE,
                )
                _sync_document_batch(
                    document_ids=[document.id for document in document_batch],
                    db_session=db_session,
                )
                if cursor is None:
                    break

            # if there are no connectors, then delete the document set. Otherwise, just
            # mark it as successfully synced.
            document_set = cast(
                DocumentSet,
                get_document_set_by_id(
                    db_session=db_session, document_set_id=document_set_id
                ),
            )  # casting since we "know" a document set with this ID exists
            if not document_set.connector_credential_pairs:
                delete_document_set(
                    document_set_row=document_set, db_session=db_session
                )
                logger.info(
                    f"Successfully deleted document set with ID: '{document_set_id}'!"
                )
            else:
                mark_document_set_as_synced(
                    document_set_id=document_set_id, db_session=db_session
                )
                logger.info(f"Document set sync for '{document_set_id}' complete!")

        except Exception:
            logger.exception("Failed to sync document set %s", document_set_id)
            raise


#####
# Periodic Tasks
#####
@celery_app.task(
    name="check_for_document_sets_sync_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_for_document_sets_sync_task() -> None:
    """Runs periodically to check if any sync tasks should be run and adds them
    to the queue"""
    with Session(get_sqlalchemy_engine()) as db_session:
        # check if any document sets are not synced
        document_set_info = fetch_document_sets(
            user_id=None, db_session=db_session, include_outdated=True
        )
        for document_set, _ in document_set_info:
            if should_sync_doc_set(document_set, db_session):
                logger.info(f"Syncing the {document_set.name} document set")
                sync_document_set_task.apply_async(
                    kwargs=dict(document_set_id=document_set.id),
                )


@celery_app.task(
    name="check_for_cc_pair_deletion_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_for_cc_pair_deletion_task() -> None:
    """Runs periodically to check if any deletion tasks should be run"""
    with Session(get_sqlalchemy_engine()) as db_session:
        # check if any document sets are not synced
        cc_pairs = get_connector_credential_pairs(db_session)
        for cc_pair in cc_pairs:
            if should_kick_off_deletion_of_cc_pair(cc_pair, db_session):
                logger.notice(f"Deleting the {cc_pair.name} connector credential pair")
                cleanup_connector_credential_pair_task.apply_async(
                    kwargs=dict(
                        connector_id=cc_pair.connector.id,
                        credential_id=cc_pair.credential.id,
                    ),
                )


@celery_app.task(
    name="kombu_message_cleanup_task",
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    base=AbortableTask,
)
def kombu_message_cleanup_task(self: Any) -> int:
    """Runs periodically to clean up the kombu_message table"""

    # we will select messages older than this amount to clean up
    KOMBU_MESSAGE_CLEANUP_AGE = 7  # days
    KOMBU_MESSAGE_CLEANUP_PAGE_LIMIT = 1000

    ctx = {}
    ctx["last_processed_id"] = 0
    ctx["deleted"] = 0
    ctx["cleanup_age"] = KOMBU_MESSAGE_CLEANUP_AGE
    ctx["page_limit"] = KOMBU_MESSAGE_CLEANUP_PAGE_LIMIT
    with Session(get_sqlalchemy_engine()) as db_session:
        # Exit the task if we can't take the advisory lock
        result = db_session.execute(
            text("SELECT pg_try_advisory_lock(:id)"),
            {"id": PostgresAdvisoryLocks.KOMBU_MESSAGE_CLEANUP_LOCK_ID.value},
        ).scalar()
        if not result:
            return 0

        while True:
            if self.is_aborted():
                raise TaskRevokedError("kombu_message_cleanup_task was aborted.")

            b = kombu_message_cleanup_task_helper(ctx, db_session)
            if not b:
                break

            db_session.commit()

    if ctx["deleted"] > 0:
        logger.info(f"Deleted {ctx['deleted']} orphaned messages from kombu_message.")

    return ctx["deleted"]


def kombu_message_cleanup_task_helper(ctx: dict, db_session: Session) -> bool:
    """
    Helper function to clean up old messages from the `kombu_message` table that are no longer relevant.

    This function retrieves messages from the `kombu_message` table that are no longer visible and
    older than a specified interval. It checks if the corresponding task_id exists in the
    `celery_taskmeta` table. If the task_id does not exist, the message is deleted.

    Args:
        ctx (dict): A context dictionary containing configuration parameters such as:
            - 'cleanup_age' (int): The age in days after which messages are considered old.
            - 'page_limit' (int): The maximum number of messages to process in one batch.
            - 'last_processed_id' (int): The ID of the last processed message to handle pagination.
            - 'deleted' (int): A counter to track the number of deleted messages.
        db_session (Session): The SQLAlchemy database session for executing queries.

    Returns:
        bool: Returns True if there are more rows to process, False if not.
    """

    query = text(
        """
    SELECT id, timestamp, payload
    FROM kombu_message WHERE visible = 'false'
    AND timestamp < CURRENT_TIMESTAMP - INTERVAL :interval_days
    AND id > :last_processed_id
    ORDER BY id
    LIMIT :page_limit
"""
    )
    kombu_messages = db_session.execute(
        query,
        {
            "interval_days": f"{ctx['cleanup_age']} days",
            "page_limit": ctx["page_limit"],
            "last_processed_id": ctx["last_processed_id"],
        },
    ).fetchall()

    if len(kombu_messages) == 0:
        return False

    for msg in kombu_messages:
        payload = json.loads(msg[2])
        task_id = payload["headers"]["id"]

        # Check if task_id exists in celery_taskmeta
        task_exists = db_session.execute(
            text("SELECT 1 FROM celery_taskmeta WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()

        # If task_id does not exist, delete the message
        if not task_exists:
            result = db_session.execute(
                text("DELETE FROM kombu_message WHERE id = :message_id"),
                {"message_id": msg[0]},
            )
            if result.rowcount > 0:  # type: ignore
                ctx["deleted"] += 1
        else:
            task_name = payload["headers"]["task"]
            logger.warning(
                f"Message found for task older than {ctx['cleanup_age']} days. "
                f"id={task_id} name={task_name}"
            )

        ctx["last_processed_id"] = msg[0]

    return True


@celery_app.task(
    name="check_for_prune_task",
    soft_time_limit=JOB_TIMEOUT,
)
def check_for_prune_task() -> None:
    """Runs periodically to check if any prune tasks should be run and adds them
    to the queue"""

    with Session(get_sqlalchemy_engine()) as db_session:
        all_cc_pairs = get_connector_credential_pairs(db_session)

        for cc_pair in all_cc_pairs:
            if should_prune_cc_pair(
                connector=cc_pair.connector,
                credential=cc_pair.credential,
                db_session=db_session,
            ):
                logger.info(f"Pruning the {cc_pair.connector.name} connector")

                prune_documents_task.apply_async(
                    kwargs=dict(
                        connector_id=cc_pair.connector.id,
                        credential_id=cc_pair.credential.id,
                    )
                )


#####
# Celery Beat (Periodic Tasks) Settings
#####
celery_app.conf.beat_schedule = {
    "check-for-document-set-sync": {
        "task": "check_for_document_sets_sync_task",
        "schedule": timedelta(seconds=5),
    },
    "check-for-cc-pair-deletion": {
        "task": "check_for_cc_pair_deletion_task",
        # don't need to check too often, since we kick off a deletion initially
        # during the API call that actually marks the CC pair for deletion
        "schedule": timedelta(minutes=1),
    },
}
celery_app.conf.beat_schedule.update(
    {
        "check-for-prune": {
            "task": "check_for_prune_task",
            "schedule": timedelta(seconds=5),
        },
    }
)
celery_app.conf.beat_schedule.update(
    {
        "kombu-message-cleanup": {
            "task": "kombu_message_cleanup_task",
            "schedule": timedelta(seconds=3600),
        },
    }
)
