import os
from datetime import timedelta
from pathlib import Path
from typing import cast

from celery import Celery  # type: ignore
from sqlalchemy.orm import Session

from danswer.background.connector_deletion import delete_connector_credential_pair
from danswer.background.task_utils import build_celery_task_wrapper
from danswer.background.task_utils import name_cc_cleanup_task
from danswer.background.task_utils import name_document_set_sync_task
from danswer.configs.app_configs import FILE_CONNECTOR_TMP_STORAGE_PATH
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.connectors.file.utils import file_age_in_hours
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.deletion_attempt import check_deletion_attempt_is_allowed
from danswer.db.document import prepare_to_modify_documents
from danswer.db.document_set import delete_document_set
from danswer.db.document_set import fetch_document_sets
from danswer.db.document_set import fetch_document_sets_for_documents
from danswer.db.document_set import fetch_documents_for_document_set
from danswer.db.document_set import get_document_set_by_id
from danswer.db.document_set import mark_document_set_as_synced
from danswer.db.engine import build_connection_string
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.engine import SYNC_DB_API
from danswer.db.models import DocumentSet
from danswer.db.tasks import check_live_task_not_timed_out
from danswer.db.tasks import get_latest_task
from danswer.document_index.document_index_utils import get_both_index_names
from danswer.document_index.factory import get_default_document_index
from danswer.document_index.interfaces import UpdateRequest
from danswer.utils.batching import batch_generator
from danswer.utils.logger import setup_logger

logger = setup_logger()

connection_string = build_connection_string(db_api=SYNC_DB_API)
celery_broker_url = f"sqla+{connection_string}"
celery_backend_url = f"db+{connection_string}"
celery_app = Celery(__name__, broker=celery_broker_url, backend=celery_backend_url)


_SYNC_BATCH_SIZE = 1000


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
        if not cc_pair or not check_deletion_attempt_is_allowed(
            connector_credential_pair=cc_pair
        ):
            raise ValueError(
                "Cannot run deletion attempt - connector_credential_pair is not deletable. "
                "This is likely because there is an ongoing / planned indexing attempt OR the "
                "connector is not disabled."
            )

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


@build_celery_task_wrapper(name_document_set_sync_task)
@celery_app.task(soft_time_limit=JOB_TIMEOUT)
def sync_document_set_task(document_set_id: int) -> None:
    """For document sets marked as not up to date, sync the state from postgres
    into the datastore. Also handles deletions."""

    def _sync_document_batch(document_ids: list[str], db_session: Session) -> None:
        logger.debug(f"Syncing document sets for: {document_ids}")

        # Acquires a lock on the documents so that no other process can modify them
        prepare_to_modify_documents(db_session=db_session, document_ids=document_ids)

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

        # Commit to release the locks
        db_session.commit()

    with Session(get_sqlalchemy_engine()) as db_session:
        try:
            documents_to_update = fetch_documents_for_document_set(
                document_set_id=document_set_id,
                db_session=db_session,
                current_only=False,
            )
            for document_batch in batch_generator(
                documents_to_update, _SYNC_BATCH_SIZE
            ):
                _sync_document_batch(
                    document_ids=[document.id for document in document_batch],
                    db_session=db_session,
                )

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
    """Runs periodically to check if any document sets are out of sync
    Creates a task to sync the set if needed"""
    with Session(get_sqlalchemy_engine()) as db_session:
        # check if any document sets are not synced
        document_set_info = fetch_document_sets(
            user_id=None, db_session=db_session, include_outdated=True
        )
        for document_set, _ in document_set_info:
            if not document_set.is_up_to_date:
                task_name = name_document_set_sync_task(document_set.id)
                latest_sync = get_latest_task(task_name, db_session)

                if latest_sync and check_live_task_not_timed_out(
                    latest_sync, db_session
                ):
                    logger.info(
                        f"Document set '{document_set.id}' is already syncing. Skipping."
                    )
                    continue

                logger.info(f"Document set {document_set.id} syncing now!")
                sync_document_set_task.apply_async(
                    kwargs=dict(document_set_id=document_set.id),
                )


@celery_app.task(name="clean_old_temp_files_task", soft_time_limit=JOB_TIMEOUT)
def clean_old_temp_files_task(
    age_threshold_in_hours: float | int = 24 * 7,  # 1 week,
    base_path: Path | str = FILE_CONNECTOR_TMP_STORAGE_PATH,
) -> None:
    """Files added via the File connector need to be deleted after ingestion
    Currently handled async of the indexing job"""
    os.makedirs(base_path, exist_ok=True)
    for file in os.listdir(base_path):
        full_file_path = Path(base_path) / file
        if file_age_in_hours(full_file_path) > age_threshold_in_hours:
            logger.info(f"Cleaning up uploaded file: {full_file_path}")
            os.remove(full_file_path)


#####
# Celery Beat (Periodic Tasks) Settings
#####
celery_app.conf.beat_schedule = {
    "check-for-document-set-sync": {
        "task": "check_for_document_sets_sync_task",
        "schedule": timedelta(seconds=5),
    },
}
