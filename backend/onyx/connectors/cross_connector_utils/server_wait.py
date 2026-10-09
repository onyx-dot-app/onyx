"""Policy for waits that a remote server asks a connector to do.

Every deployment honours the server delay and logs long delays. Only
multi-tenant (cloud) deployments cap the delay, because there a hostile
server could pin shared workers.
"""

import math
from enum import Enum

from onyx.server.metrics.connector_retry_after_metrics import (
    inc_connector_long_retry_after,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

MAX_SERVER_WAIT_SECONDS = 86400.0

# Stable prefixes for log-based alerts.
SERVER_WAIT_CAPPED_LOG_PREFIX = "CONNECTOR_RETRY_AFTER_CAPPED"
SERVER_WAIT_LONG_LOG_PREFIX = "CONNECTOR_RETRY_AFTER_LONG"


class ServerWaitClass(str, Enum):
    OVER_1M = "over_1m"
    OVER_5M = "over_5m"
    CAPPED = "capped"


def bound_server_wait(seconds: float, source: str, *, classify: bool = True) -> float:
    """Return the wait to use for a server-requested delay of ``seconds``.

    ``source`` is a fixed connector family name (metric label). Set
    ``classify=False`` when the same delay was already classified, so a
    re-read does not count twice.
    """
    if math.isnan(seconds) or seconds < 0:
        return 0.0

    if classify and seconds > 60:
        wait_class = (
            ServerWaitClass.OVER_5M if seconds > 300 else ServerWaitClass.OVER_1M
        )
        logger.warning(
            "%s class=%s source=%s requested_s=%.1f tenant_id=%s",
            SERVER_WAIT_LONG_LOG_PREFIX,
            wait_class.value,
            source,
            seconds,
            get_current_tenant_id(),
        )
        inc_connector_long_retry_after(source, wait_class.value)

    if MULTI_TENANT and seconds > MAX_SERVER_WAIT_SECONDS:
        logger.error(
            "%s source=%s requested_s=%.1f cap_s=%.1f tenant_id=%s",
            SERVER_WAIT_CAPPED_LOG_PREFIX,
            source,
            seconds,
            MAX_SERVER_WAIT_SECONDS,
            get_current_tenant_id(),
        )
        inc_connector_long_retry_after(source, ServerWaitClass.CAPPED.value)
        return MAX_SERVER_WAIT_SECONDS

    return seconds
