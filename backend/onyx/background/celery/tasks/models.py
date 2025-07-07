from enum import Enum

from pydantic import BaseModel


class DocProcessingContext(BaseModel):
    tenant_id: str
    cc_pair_id: int
    search_settings_id: int
    index_attempt_id: int


class IndexingWatchdogTerminalStatus(str, Enum):
    """The different statuses the watchdog can finish with.

    TODO: create broader success/failure/abort categories
    """

    UNDEFINED = "undefined"

    SUCCEEDED = "succeeded"

    SPAWN_FAILED = "spawn_failed"  # connector spawn failed
    SPAWN_NOT_ALIVE = (
        "spawn_not_alive"  # spawn succeeded but process did not come alive
    )

    BLOCKED_BY_DELETION = "blocked_by_deletion"
    BLOCKED_BY_STOP_SIGNAL = "blocked_by_stop_signal"
    FENCE_NOT_FOUND = "fence_not_found"  # fence does not exist
    FENCE_READINESS_TIMEOUT = (
        "fence_readiness_timeout"  # fence exists but wasn't ready within the timeout
    )
    FENCE_MISMATCH = "fence_mismatch"  # task and fence metadata mismatch
    TASK_ALREADY_RUNNING = "task_already_running"  # task appears to be running already
    INDEX_ATTEMPT_MISMATCH = (
        "index_attempt_mismatch"  # expected index attempt metadata not found in db
    )

    CONNECTOR_VALIDATION_ERROR = (
        "connector_validation_error"  # the connector validation failed
    )
    CONNECTOR_EXCEPTIONED = "connector_exceptioned"  # the connector itself exceptioned
    WATCHDOG_EXCEPTIONED = "watchdog_exceptioned"  # the watchdog exceptioned

    # the watchdog received a termination signal
    TERMINATED_BY_SIGNAL = "terminated_by_signal"

    # the watchdog terminated the task due to no activity
    TERMINATED_BY_ACTIVITY_TIMEOUT = "terminated_by_activity_timeout"

    # NOTE: this may actually be the same as SIGKILL, but parsed differently by python
    # consolidate once we know more
    OUT_OF_MEMORY = "out_of_memory"

    PROCESS_SIGNAL_SIGKILL = "process_signal_sigkill"

    @property
    def code(self) -> int:
        _ENUM_TO_CODE: dict[IndexingWatchdogTerminalStatus, int] = {
            IndexingWatchdogTerminalStatus.PROCESS_SIGNAL_SIGKILL: -9,
            IndexingWatchdogTerminalStatus.OUT_OF_MEMORY: 137,
            IndexingWatchdogTerminalStatus.CONNECTOR_VALIDATION_ERROR: 247,
            IndexingWatchdogTerminalStatus.BLOCKED_BY_DELETION: 248,
            IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL: 249,
            IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND: 250,
            IndexingWatchdogTerminalStatus.FENCE_READINESS_TIMEOUT: 251,
            IndexingWatchdogTerminalStatus.FENCE_MISMATCH: 252,
            IndexingWatchdogTerminalStatus.TASK_ALREADY_RUNNING: 253,
            IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH: 254,
            IndexingWatchdogTerminalStatus.CONNECTOR_EXCEPTIONED: 255,
        }

        return _ENUM_TO_CODE[self]

    @classmethod
    def from_code(cls, code: int) -> "IndexingWatchdogTerminalStatus":
        _CODE_TO_ENUM: dict[int, IndexingWatchdogTerminalStatus] = {
            -9: IndexingWatchdogTerminalStatus.PROCESS_SIGNAL_SIGKILL,
            137: IndexingWatchdogTerminalStatus.OUT_OF_MEMORY,
            247: IndexingWatchdogTerminalStatus.CONNECTOR_VALIDATION_ERROR,
            248: IndexingWatchdogTerminalStatus.BLOCKED_BY_DELETION,
            249: IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL,
            250: IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND,
            251: IndexingWatchdogTerminalStatus.FENCE_READINESS_TIMEOUT,
            252: IndexingWatchdogTerminalStatus.FENCE_MISMATCH,
            253: IndexingWatchdogTerminalStatus.TASK_ALREADY_RUNNING,
            254: IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH,
            255: IndexingWatchdogTerminalStatus.CONNECTOR_EXCEPTIONED,
        }

        if code in _CODE_TO_ENUM:
            return _CODE_TO_ENUM[code]

        return IndexingWatchdogTerminalStatus.UNDEFINED


class SimpleJobResult:
    """The data we want to have when the watchdog finishes"""

    def __init__(self) -> None:
        self.status = IndexingWatchdogTerminalStatus.UNDEFINED
        self.connector_source = None
        self.exit_code = None
        self.exception_str = None

    status: IndexingWatchdogTerminalStatus
    connector_source: str | None
    exit_code: int | None
    exception_str: str | None
