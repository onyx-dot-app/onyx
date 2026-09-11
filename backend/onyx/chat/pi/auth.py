"""Service authentication for tenant-scoped agent callbacks."""

import os
import secrets
from collections.abc import AsyncIterator

from fastapi import Request

from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


async def worker_identity(request: Request) -> AsyncIterator[None]:
    expected = os.environ.get("ONYX_AGENT_SERVICE_TOKEN", "")
    if not expected or not secrets.compare_digest(
        request.headers.get("authorization", ""), f"Bearer {expected}"
    ):
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
    tenant = request.headers.get("x-onyx-tenant-id", "")
    if not tenant or not is_valid_schema_name(tenant):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid agent tenant")
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
