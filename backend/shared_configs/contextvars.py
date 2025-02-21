import contextvars

from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


# Context variable for the current tenant id
CURRENT_TENANT_ID_CONTEXTVAR: contextvars.ContextVar[
    str | None
] = contextvars.ContextVar(
    "current_tenant_id", default=None if MULTI_TENANT else POSTGRES_DEFAULT_SCHEMA
)


"""Utils related to contextvars"""


def get_current_tenant_id() -> str:
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if tenant_id is None:
        raise RuntimeError("Tenant ID is not set. This should never happen.")
    return tenant_id
