"""Config-driven document push, available in all editions.

Pushes successfully indexed documents to an operator-configured HTTP endpoint
(DOCUMENT_PUSH_ENDPOINT_URL et al. in app_configs). This is not a hook: it does
not read the hook table and is not managed via the EE /admin/hooks API. It
reuses the hook framework's payload shape (DocumentPushPayload) and HTTP
machinery (execute_hook_endpoint). The two sinks are either/or, never both:
the call site checks this config first (a cached local read) and only falls
back to the DOCUMENT_PUSH hook when it is unset.

Unlike the hook (single-tenant only), this sink also runs in multi-tenant
deployments — the endpoint is deployment-wide and operator-owned, so
receiving documents from all tenants is the expected behavior. Note the
payload carries no tenant identifier.

The endpoint URL is operator-supplied through the environment, so unlike
admin-entered hook URLs it is trusted to point at private-network destinations
— pushing to an internal system is the primary use case. Scheme and structural
validation still apply.

Push failures never fail the indexing batch: the fail strategy is fixed to
SOFT and unexpected errors are swallowed after logging.
"""

from functools import lru_cache

from onyx.configs.app_configs import DOCUMENT_PUSH_API_KEY
from onyx.configs.app_configs import DOCUMENT_PUSH_ENDPOINT_URL
from onyx.configs.app_configs import DOCUMENT_PUSH_TIMEOUT_SECONDS
from onyx.db.enums import HookFailStrategy
from onyx.hooks.http_executor import execute_hook_endpoint
from onyx.hooks.http_executor import HookEndpointConfig
from onyx.hooks.points.document_push import DocumentPushPayload
from onyx.hooks.points.document_push import DocumentPushResponse
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_outbound_http_url

logger = setup_logger()


@lru_cache(maxsize=1)
def get_document_push_config() -> HookEndpointConfig | None:
    """Build the endpoint config from the environment, or None when unset.

    An invalid URL disables the feature and logs an error (once, via the
    cache) rather than raising — a misconfigured push destination must not
    take down indexing.
    """
    if not DOCUMENT_PUSH_ENDPOINT_URL:
        return None
    try:
        endpoint_url = validate_outbound_http_url(
            DOCUMENT_PUSH_ENDPOINT_URL, allow_private_network=True
        )
    except (SSRFException, ValueError):
        logger.exception(
            "DOCUMENT_PUSH_ENDPOINT_URL is invalid — config-driven document "
            "push is disabled"
        )
        return None
    return HookEndpointConfig(
        endpoint_url=endpoint_url,
        api_key=DOCUMENT_PUSH_API_KEY,
        timeout_seconds=DOCUMENT_PUSH_TIMEOUT_SECONDS,
        # Fire-and-forget: a push failure must never fail the indexing batch.
        fail_strategy=HookFailStrategy.SOFT,
    )


def push_document_via_config(payload: DocumentPushPayload) -> None:
    """POST one indexed document to the configured endpoint.

    No-op when DOCUMENT_PUSH_ENDPOINT_URL is unset. Never raises.
    """
    config = get_document_push_config()
    if config is None:
        return
    try:
        execute_hook_endpoint(
            config=config,
            payload=payload.model_dump(),
            response_type=DocumentPushResponse,
        )
    except Exception:
        # SOFT strategy already absorbs HTTP/validation failures; this guards
        # against unexpected errors so indexing is never affected.
        logger.exception(
            "Unexpected error pushing document_id=%s to the configured endpoint",
            payload.document_id,
        )
