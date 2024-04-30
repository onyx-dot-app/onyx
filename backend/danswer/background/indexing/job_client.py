"""Custom client that works similarly to Dask, but simpler and more lightweight.
Dask jobs behaved very strangely - they would die all the time, retries would
not follow the expected behavior, etc.

NOTE: cannot use Celery directly due to
https://github.com/celery/celery/issues/7007#issuecomment-1740139367"""
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing import Process
from typing import Any
from typing import Literal
from typing import Optional

from danswer.db.engine import get_sqlalchemy_engine
from danswer.utils.logger import setup_logger

logger = setup_logger()

JobStatusType = (
    Literal["error"]
    | Literal["finished"]
    | Literal["pending"]
    | Literal["running"]
    | Literal["cancelled"]
)


def _initializer(
    func: Callable, args: list | tuple, kwargs: dict[str, Any] | None = None
) -> Any:
    """Ensure the parent proc's database connections are not touched
    in the new connection pool

    Based on the recommended approach in the SQLAlchemy docs found:
    https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork
    """
    if kwargs is None:
        kwargs = {}

    get_sqlalchemy_engine().dispose(close=False)
    return func(*args, **kwargs)


@dataclass
class SimpleJob:
    """Drop in replacement for `dask.distributed.Future`"""

    id: int
    process: Optional["Process"] = None

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
        elif self.process.exitcode > 0:
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
        return (
            f"Job with ID '{self.id}' was killed or encountered an unhandled exception."
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
            logger.debug("No available workers to run job")
            return None

        job_id = self.job_id_counter
        self.job_id_counter += 1

        process = Process(target=_initializer(func=func, args=args), daemon=True)
        job = SimpleJob(id=job_id, process=process)
        process.start()

        self.jobs[job_id] = job

        return job
