"""Custom client that works similarly to Dask, but simpler and more lightweight.
Dask jobs behaved very strangely - they would die all the time, retries would
not follow the expected behavior, etc.

NOTE: cannot use Celery directly due to
https://github.com/celery/celery/issues/7007#issuecomment-1740139367"""

import multiprocessing as mp
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.context import SpawnProcess
from typing import Any
from typing import Literal
from typing import Optional

from onyx.configs.constants import POSTGRES_CELERY_WORKER_INDEXING_CHILD_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import TENANT_ID_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class SimpleJobException(Exception):
    """lets us raise an exception that will return a specific error code"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        code: int | None = kwargs.pop("code", None)
        self.code = code
        super().__init__(*args, **kwargs)


JobStatusType = (
    Literal["error"]
    | Literal["finished"]
    | Literal["pending"]
    | Literal["running"]
    | Literal["cancelled"]
)


def _initializer(
    func: Callable,
    queue: mp.Queue,
    args: list | tuple,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Initialize the child process with a fresh SQLAlchemy Engine.

    Based on SQLAlchemy's recommendations to handle multiprocessing:
    https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork
    """
    if kwargs is None:
        kwargs = {}

    logger.info("Initializing spawned worker child process.")
    # 1. Get tenant_id from args or fallback to default
    tenant_id = POSTGRES_DEFAULT_SCHEMA
    for arg in reversed(args):
        if isinstance(arg, str) and arg.startswith(TENANT_ID_PREFIX):
            tenant_id = arg
            break

    # 2. Set the tenant context before running anything
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    # Reset the engine in the child process
    SqlEngine.reset_engine()

    # Optionally set a custom app name for database logging purposes
    SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_INDEXING_CHILD_APP_NAME)

    # Initialize a new engine with desired parameters
    SqlEngine.init_engine(
        pool_size=4, max_overflow=12, pool_recycle=60, pool_pre_ping=True
    )

    # Proceed with executing the target function
    try:
        return func(*args, **kwargs)
    except SimpleJobException as e:
        logger.exception("SimpleJob raised a SimpleJobException")
        error_msg = traceback.format_exc()
        queue.put(error_msg)  # Send the exception to the parent process

        sys.exit(e.code)  # use the given exit code
    except Exception:
        logger.exception("SimpleJob raised an exception")
        error_msg = traceback.format_exc()
        queue.put(error_msg)  # Send the exception to the parent process

        sys.exit(255)  # use 255 to indicate a generic exception
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _run_in_process(
    func: Callable,
    queue: mp.Queue,
    args: list | tuple,
    kwargs: dict[str, Any] | None = None,
) -> None:
    _initializer(func, queue, args, kwargs)


@dataclass
class SimpleJob:
    """Drop in replacement for `dask.distributed.Future`"""

    id: int
    process: Optional["SpawnProcess"] = None
    queue: Optional[mp.Queue] = None
    _exception: Optional[str] = None

    def cancel(self) -> bool:
        return self.release()

    def release(self) -> bool:
        if self.process is not None and self.process.is_alive():
            self.process.terminate()
            return True
        return False

    @property
    def status(self) -> JobStatusType:
        if not self.process:
            return "pending"
        elif self.process.is_alive():
            return "running"
        elif self.process.exitcode is None:
            return "cancelled"
        elif self.process.exitcode != 0:
            return "error"
        else:
            return "finished"

    def done(self) -> bool:
        return (
            self.status == "finished"
            or self.status == "cancelled"
            or self.status == "error"
        )

    def exception(self) -> str:
        """Needed to match the Dask API, but not implemented since we don't currently
        have a way to get back the exception information from the child process."""

        """Retrieve exception from the multiprocessing queue if available."""
        if self._exception is None and self.queue and not self.queue.empty():
            self._exception = self.queue.get()  # Get exception from queue

        return (
            self._exception or f"Job with ID '{self.id}' did not report an exception."
        )


class SimpleJobClient:
    """Drop in replacement for `dask.distributed.Client`"""

    def __init__(self, n_workers: int = 1) -> None:
        self.n_workers = n_workers
        self.job_id_counter = 0
        self.jobs: dict[int, SimpleJob] = {}

    def _cleanup_completed_jobs(self) -> None:
        current_job_ids = list(self.jobs.keys())
        for job_id in current_job_ids:
            job = self.jobs.get(job_id)
            if job and job.done():
                logger.debug(f"Cleaning up job with id: '{job.id}'")
                del self.jobs[job.id]

    def submit(self, func: Callable, *args: Any, pure: bool = True) -> SimpleJob | None:
        """NOTE: `pure` arg is needed so this can be a drop in replacement for Dask"""
        self._cleanup_completed_jobs()
        if len(self.jobs) >= self.n_workers:
            logger.debug(
                f"No available workers to run job. "
                f"Currently running '{len(self.jobs)}' jobs, with a limit of '{self.n_workers}'."
            )
            return None

        job_id = self.job_id_counter
        self.job_id_counter += 1

        # this approach allows us to always "spawn" a new process regardless of
        # get_start_method's current setting
        ctx = mp.get_context("spawn")
        queue = ctx.Queue()
        process = ctx.Process(
            target=_run_in_process, args=(func, queue, args), daemon=True
        )
        job = SimpleJob(id=job_id, process=process, queue=queue)
        process.start()

        self.jobs[job_id] = job

        return job
