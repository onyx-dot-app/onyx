from sqlalchemy import text

from onyx.db.engine.sql_engine import get_session_with_shared_schema
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import TENANT_ID_PREFIX


def get_all_tenant_ids() -> list[str]:
    """Returning [None] means the only tenant is the 'public' or self hosted tenant."""

    tenant_ids: list[str]

    if not MULTI_TENANT:
        return [POSTGRES_DEFAULT_SCHEMA]

    with get_session_with_shared_schema() as session:
        result = session.execute(
            text(
                f"""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', '{POSTGRES_DEFAULT_SCHEMA}')"""
            )
        )
        tenant_ids = [row[0] for row in result]

    valid_tenants = [
        tenant
        for tenant in tenant_ids
        if tenant is None or tenant.startswith(TENANT_ID_PREFIX)
    ]
    return valid_tenants
