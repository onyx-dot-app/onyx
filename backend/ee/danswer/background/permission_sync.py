import logging
import time
from datetime import datetime

import dask
from dask.distributed import Client
from dask.distributed import Future
from distributed import LocalCluster
from sqlalchemy.orm import Session

from danswer.background.indexing.dask_utils import ResourceLogger
from danswer.background.indexing.job_client import SimpleJob
from danswer.background.indexing.job_client import SimpleJobClient
from danswer.configs.app_configs import CLEANUP_INDEXING_JOBS_TIMEOUT
from danswer.configs.app_configs import DASK_JOB_CLIENT_ENABLED
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import POSTGRES_PERMISSIONS_APP_NAME
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.engine import init_sqlalchemy_engine
from danswer.db.models import PermissionSyncStatus
from danswer.utils.logger import setup_logger
from ee.danswer.configs.app_configs import NUM_PERMISSION_WORKERS
from ee.danswer.connectors.factory import CONNECTOR_PERMISSION_FUNC_MAP
from ee.danswer.db.connector import fetch_sources_with_connectors
from ee.danswer.db.connector_credential_pair import get_cc_pairs_by_source
from ee.danswer.db.permission_sync import create_perm_sync
from ee.danswer.db.permission_sync import expire_perm_sync_timed_out
from ee.danswer.db.permission_sync import get_perm_sync_attempt
from ee.danswer.db.permission_sync import mark_all_inprogress_permission_sync_failed
from shared_configs.configs import LOG_LEVEL

logger = setup_logger()

# If the indexing dies, it's most likely due to resource constraints,
# restarting just delays the eventual failure, not useful to the user
dask.config.set({"distributed.scheduler.allowed-failures": 0})


def cleanup_perm_sync_jobs(
    existing_jobs: dict[tuple[int, int | DocumentSource], Future | SimpleJob],
    # Just reusing the same timeout, fine for now
    timeout_hours: int = CLEANUP_INDEXING_JOBS_TIMEOUT,
) -> dict[tuple[int, int | DocumentSource], Future | SimpleJob]:
    existing_jobs_copy = existing_jobs.copy()

    with Session(get_sqlalchemy_engine()) as db_session:
        # clean up completed jobs
        for (attempt_id, details), job in existing_jobs.items():
            perm_sync_attempt = get_perm_sync_attempt(
                attempt_id=attempt_id, db_session=db_session
            )

            # do nothing for ongoing jobs that haven't been stopped
            if (
                not job.done()
                and perm_sync_attempt.status == PermissionSyncStatus.IN_PROGRESS
            ):
                continue

            if job.status == "error":
                logger.error(job.exception())

            job.release()
            del existing_jobs_copy[(attempt_id, details)]

        # clean up in-progress jobs that were never completed
        expire_perm_sync_timed_out(
            timeout_hours=timeout_hours,
            db_session=db_session,
        )

    return existing_jobs_copy


def create_group_sync_jobs(
    existing_jobs: dict[tuple[int, int | DocumentSource], Future | SimpleJob],
    client: Client | SimpleJobClient,
) -> dict[tuple[int, int | DocumentSource], Future | SimpleJob]:
    """Creates new relational DB group permission sync job for each source that:
    - has permission sync enabled
    - has at least 1 connector (enabled or paused)
    - has no sync already running
    """
    existing_jobs_copy = existing_jobs.copy()
    sources_w_runs = [
        key[1]
        for key in existing_jobs_copy.keys()
        if isinstance(key[1], DocumentSource)
    ]
    with Session(get_sqlalchemy_engine()) as db_session:
        sources_w_connector = fetch_sources_with_connectors(db_session)
        for source_type in sources_w_connector:
            if source_type not in CONNECTOR_PERMISSION_FUNC_MAP:
                continue
            if source_type in sources_w_runs:
                continue

            db_group_fnc, _ = CONNECTOR_PERMISSION_FUNC_MAP[source_type]
            perm_sync = create_perm_sync(
                source_type=source_type,
                group_update=True,
                cc_pair_id=None,
                db_session=db_session,
            )

            run = client.submit(db_group_fnc, pure=False)

            logger.info(
                f"Kicked off group permission sync for source type {source_type}"
            )

            if run:
                existing_jobs_copy[(perm_sync.id, source_type)] = run

    return existing_jobs_copy


def create_connector_perm_sync_jobs(
    existing_jobs: dict[tuple[int, int | DocumentSource], Future | SimpleJob],
    client: Client | SimpleJobClient,
) -> dict[tuple[int, int | DocumentSource], Future | SimpleJob]:
    """Update Document Index ACL sync job for each cc-pair where:
    - source type has permission sync enabled
    - has no sync already running
    """
    existing_jobs_copy = existing_jobs.copy()
    cc_pairs_w_runs = [
        key[1]
        for key in existing_jobs_copy.keys()
        if isinstance(key[1], DocumentSource)
    ]
    with Session(get_sqlalchemy_engine()) as db_session:
        sources_w_connector = fetch_sources_with_connectors(db_session)
        for source_type in sources_w_connector:
            if source_type not in CONNECTOR_PERMISSION_FUNC_MAP:
                continue

            _, index_sync_fnc = CONNECTOR_PERMISSION_FUNC_MAP[source_type]

            cc_pairs = get_cc_pairs_by_source(source_type, db_session)

            for cc_pair in cc_pairs:
                if cc_pair.id in cc_pairs_w_runs:
                    continue

                perm_sync = create_perm_sync(
                    source_type=source_type,
                    group_update=False,
                    cc_pair_id=cc_pair.id,
                    db_session=db_session,
                )

                run = client.submit(index_sync_fnc, cc_pair.id, pure=False)

                logger.info(f"Kicked off ACL sync for cc-pair {cc_pair.id}")

                if run:
                    existing_jobs_copy[(perm_sync.id, cc_pair.id)] = run

    return existing_jobs_copy


def permission_loop(delay: int = 60, num_workers: int = NUM_PERMISSION_WORKERS) -> None:
    client: Client | SimpleJobClient
    if DASK_JOB_CLIENT_ENABLED:
        cluster_primary = LocalCluster(
            n_workers=num_workers,
            threads_per_worker=1,
            # there are warning about high memory usage + "Event loop unresponsive"
            # which are not relevant to us since our workers are expected to use a
            # lot of memory + involve CPU intensive tasks that will not relinquish
            # the event loop
            silence_logs=logging.ERROR,
        )
        client = Client(cluster_primary)
        if LOG_LEVEL.lower() == "debug":
            client.register_worker_plugin(ResourceLogger())
    else:
        client = SimpleJobClient(n_workers=num_workers)

    existing_jobs: dict[tuple[int, int | DocumentSource], Future | SimpleJob] = {}
    engine = get_sqlalchemy_engine()

    with Session(engine) as db_session:
        # Any jobs still in progress on restart must have died
        mark_all_inprogress_permission_sync_failed(db_session)

    while True:
        start = time.time()
        start_time_utc = datetime.utcfromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Running Permission Sync, current UTC time: {start_time_utc}")

        if existing_jobs:
            logger.debug(
                "Found existing permission sync jobs: "
                f"{[(attempt_id, job.status) for attempt_id, job in existing_jobs.items()]}"
            )

        try:
            # TODO turn this on when it works
            """
            existing_jobs = cleanup_perm_sync_jobs(existing_jobs=existing_jobs)
            existing_jobs = create_group_sync_jobs(
                existing_jobs=existing_jobs, client=client
            )
            existing_jobs = create_connector_perm_sync_jobs(
                existing_jobs=existing_jobs, client=client
            )
            """
        except Exception as e:
            logger.exception(f"Failed to run update due to {e}")
        sleep_time = delay - (time.time() - start)
        if sleep_time > 0:
            time.sleep(sleep_time)


def update__main() -> None:
    logger.notice("Starting Permission Syncing Loop")
    init_sqlalchemy_engine(POSTGRES_PERMISSIONS_APP_NAME)
    permission_loop()


if __name__ == "__main__":
    update__main()
