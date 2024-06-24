from datetime import timedelta
from typing import cast

from celery import Celery  # type: ignore
from sqlalchemy.orm import Session

from danswer.background.celery.celery_utils import extract_ids_from_runnable_connector
from danswer.background.celery.celery_utils import should_prune_cc_pair
from danswer.background.celery.celery_utils import should_sync_doc_set
from danswer.background.connector_deletion import delete_connector_credential_pair
from danswer.background.connector_deletion import delete_connector_credential_pair_batch
from danswer.background.task_utils import build_celery_task_wrapper
from danswer.background.task_utils import name_cc_cleanup_task
from danswer.background.task_utils import name_cc_prune_task
from danswer.background.task_utils import name_document_set_sync_task
from danswer.configs.app_configs import JOB_TIMEOUT
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

connection_string = build_connection_string(db_api=SYNC_DB_API)
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
    """connector pruning task. For a cc pair, this task pulls all docuement IDs from the source
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
}
celery_app.conf.beat_schedule.update(
    {
        "check-for-prune": {
            "task": "check_for_prune_task",
            "schedule": timedelta(seconds=5),
        },
    }
)
