import asyncio

import psutil
from dask.distributed import WorkerPlugin
from distributed import Worker

from onyx.utils.logger import setup_logger

logger = setup_logger()


class ResourceLogger(WorkerPlugin):
    def __init__(self, log_interval: int = 60 * 5):
        self.log_interval = log_interval

    def setup(self, worker: Worker) -> None:
        """This method will be called when the plugin is attached to a worker."""
        self.worker = worker
        worker.loop.add_callback(self.log_resources)

    async def log_resources(self) -> None:
        """Periodically log CPU and memory usage.

        NOTE: must be async or else will clog up the worker indefinitely due to the fact that
        Dask uses Tornado under the hood (which is async)"""
        while True:
            cpu_percent = psutil.cpu_percent(interval=None)
            memory_available_gb = psutil.virtual_memory().available / (1024.0**3)
            # You can now log these values or send them to a monitoring service
            logger.debug(
                f"Worker {self.worker.address}: CPU usage {cpu_percent}%, Memory available {memory_available_gb}GB"
            )
            await asyncio.sleep(self.log_interval)
