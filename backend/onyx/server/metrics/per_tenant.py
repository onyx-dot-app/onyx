"""Per-tenant request counter metric.

Increments a counter on every request, labelled by tenant, so Grafana can
answer "which tenant is generating the most traffic?"
"""

from prometheus_client import Counter
from prometheus_fastapi_instrumentator.metrics import Info

from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_requests_by_tenant = Counter(
    "onyx_api_requests_by_tenant_total",
    "Total API requests by tenant",
    ["tenant_id", "method", "handler", "status"],
)


def per_tenant_request_callback(info: Info) -> None:
    """Increment per-tenant request counter for every request."""
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get() or "unknown"
    _requests_by_tenant.labels(
        tenant_id=tenant_id,
        method=info.method,
        handler=info.modified_handler,
        status=info.modified_status,
    ).inc()
