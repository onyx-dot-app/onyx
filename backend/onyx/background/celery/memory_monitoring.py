# backend/onyx/background/celery/memory_monitoring.py
import logging
import os
from logging.handlers import RotatingFileHandler

import psutil

from onyx.utils.logger import is_running_in_container
from onyx.utils.logger import setup_logger

# Regular application logger
logger = setup_logger()

# Only set up memory monitoring in container environment
if is_running_in_container():
    # Set up a dedicated memory monitoring logger
    MEMORY_LOG_DIR = "/var/log/onyx/memory"
    MEMORY_LOG_FILE = os.path.join(MEMORY_LOG_DIR, "memory_usage.log")
    MEMORY_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    MEMORY_LOG_BACKUP_COUNT = 5  # Keep 5 backup files

    # Ensure log directory exists
    os.makedirs(MEMORY_LOG_DIR, exist_ok=True)

    # Create a dedicated logger for memory monitoring
    memory_logger = logging.getLogger("memory_monitoring")
    memory_logger.setLevel(logging.INFO)

    # Create a rotating file handler
    memory_handler = RotatingFileHandler(
        MEMORY_LOG_FILE,
        maxBytes=MEMORY_LOG_MAX_BYTES,
        backupCount=MEMORY_LOG_BACKUP_COUNT,
    )

    # Create a formatter that includes all relevant information
    memory_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    memory_handler.setFormatter(memory_formatter)
    memory_logger.addHandler(memory_handler)
else:
    # Create a null logger when not in container
    memory_logger = logging.getLogger("memory_monitoring")
    memory_logger.addHandler(logging.NullHandler())


def emit_process_memory(
    pid: int, process_name: str, additional_metadata: dict[str, str | int]
) -> None:
    # Skip memory monitoring if not in container
    if not is_running_in_container():
        return

    try:
        process = psutil.Process(pid)
        memory_info = process.memory_info()
        cpu_percent = process.cpu_percent(interval=0.1)

        # Build metadata string from additional_metadata dictionary
        metadata_str = " ".join(
            [f"{key}={value}" for key, value in additional_metadata.items()]
        )
        metadata_str = f" {metadata_str}" if metadata_str else ""

        memory_logger.info(
            f"PROCESS_MEMORY process_name={process_name} pid={pid} "
            f"rss_mb={memory_info.rss / (1024 * 1024):.2f} "
            f"vms_mb={memory_info.vms / (1024 * 1024):.2f} "
            f"cpu={cpu_percent:.2f}{metadata_str}"
        )
    except Exception:
        logger.exception("Error monitoring process memory.")
