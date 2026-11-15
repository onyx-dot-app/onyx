"""Entry point for the webhook server, which receives connector events.

Whether this process runs is a deployment decision: `webhookServer.enabled`
in the Helm values, or the `webhook` Compose profile.
"""

import uvicorn

from onyx.configs.app_configs import (
    POSTGRES_API_SERVER_POOL_OVERFLOW,
    POSTGRES_API_SERVER_POOL_SIZE,
)
from onyx.db.engine.sql_engine import SqlEngine
from onyx.tracing.setup import setup_tracing
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import set_is_ee_if_available
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

POSTGRES_WEBHOOK_APP_NAME = "webhook_server"

# Matches the Helm container port and the nginx upstreams.
WEBHOOK_SERVER_HOST = "0.0.0.0"  # noqa: S104 — container bind address
WEBHOOK_SERVER_PORT = 8091


def main() -> None:
    if MULTI_TENANT:
        raise ValueError(
            "The webhook server does not support multi-tenant deployments. "
            "Nothing resolves a tenant for an unauthenticated request, so a "
            "route would read and write the public schema. Leave "
            "webhookServer.enabled false, or drop the webhook Compose profile."
        )

    set_is_ee_if_available()
    setup_tracing()

    SqlEngine.set_app_name(POSTGRES_WEBHOOK_APP_NAME)
    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )

    from onyx.webhook_server.api import webhook_app

    logger.notice(
        "Starting webhook server on %s:%s", WEBHOOK_SERVER_HOST, WEBHOOK_SERVER_PORT
    )
    uvicorn.run(webhook_app, host=WEBHOOK_SERVER_HOST, port=WEBHOOK_SERVER_PORT)


if __name__ == "__main__":
    main()
