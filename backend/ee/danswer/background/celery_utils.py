from datetime import datetime
from datetime import timezone

from sqlalchemy.orm import Session

from danswer.db.enums import AccessType
from danswer.db.models import ConnectorCredentialPair
from danswer.db.tasks import check_task_is_live_and_not_timed_out
from danswer.db.tasks import get_latest_task
from danswer.utils.logger import setup_logger
from ee.danswer.background.task_name_builders import name_chat_ttl_task
from ee.danswer.background.task_name_builders import (
    name_sync_external_doc_permissions_task,
)
from ee.danswer.background.task_name_builders import (
    name_sync_external_group_permissions_task,
)
from ee.danswer.external_permissions.sync_params import PERMISSION_SYNC_PERIODS

logger = setup_logger()


def _is_time_to_run_sync(cc_pair: ConnectorCredentialPair) -> bool:
    source_sync_period = PERMISSION_SYNC_PERIODS.get(cc_pair.connector.source)

    # If RESTRICTED_FETCH_PERIOD[source] is None, we always run the sync.
    if not source_sync_period:
        return True

    # If the last sync is None, it has never been run so we run the sync
    if cc_pair.last_time_perm_sync is None:
        return True

    last_sync = cc_pair.last_time_perm_sync.replace(tzinfo=timezone.utc)
    current_time = datetime.now(timezone.utc)

    # If the last sync is greater than the full fetch period, we run the sync
    if (current_time - last_sync).total_seconds() > source_sync_period:
        return True

    return False


def should_perform_chat_ttl_check(
    retention_limit_days: int | None, db_session: Session
) -> bool:
    # TODO: make this a check for None and add behavior for 0 day TTL
    if not retention_limit_days:
        return False

    task_name = name_chat_ttl_task(retention_limit_days)
    latest_task = get_latest_task(task_name, db_session)
    if not latest_task:
        return True

    if check_task_is_live_and_not_timed_out(latest_task, db_session):
        logger.debug(f"{task_name} is already being performed. Skipping.")
        return False
    return True


def should_perform_external_doc_permissions_check(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> bool:
    if cc_pair.access_type != AccessType.SYNC:
        return False

    task_name = name_sync_external_doc_permissions_task(cc_pair_id=cc_pair.id)

    latest_task = get_latest_task(task_name, db_session)
    if not latest_task:
        return True

    if check_task_is_live_and_not_timed_out(latest_task, db_session):
        logger.debug(f"{task_name} is already being performed. Skipping.")
        return False

    if not _is_time_to_run_sync(cc_pair):
        return False

    return True


def should_perform_external_group_permissions_check(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> bool:
    if cc_pair.access_type != AccessType.SYNC:
        return False

    task_name = name_sync_external_group_permissions_task(cc_pair_id=cc_pair.id)

    latest_task = get_latest_task(task_name, db_session)
    if not latest_task:
        return True

    if check_task_is_live_and_not_timed_out(latest_task, db_session):
        logger.debug(f"{task_name} is already being performed. Skipping.")
        return False

    if not _is_time_to_run_sync(cc_pair):
        return False

    return True
