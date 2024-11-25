import contextvars

from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

# Context variable for the current tenant id
CURRENT_TENANT_ID_CONTEXTVAR = contextvars.ContextVar(
    "current_tenant_id", default=POSTGRES_DEFAULT_SCHEMA
)
