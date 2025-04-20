import contextvars

from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


# Context variable for the current tenant id
CURRENT_TENANT_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar(
        "current_tenant_id", default=None if MULTI_TENANT else POSTGRES_DEFAULT_SCHEMA
    )
)

# set by every route in the API server
INDEXING_REQUEST_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("indexing_request_id", default=None)
)

# set by every route in the API server
ONYX_REQUEST_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "onyx_request_id", default=None
)

"""Utils related to contextvars"""


def get_current_tenant_id() -> str:
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if tenant_id is None:
        import traceback

        if not MULTI_TENANT:
            return POSTGRES_DEFAULT_SCHEMA

        stack_trace = traceback.format_stack()
        error_message = (
            "Tenant ID is not set. This should never happen.\nStack trace:\n"
            + "".join(stack_trace)
        )
        raise RuntimeError(error_message)
    return tenant_id
