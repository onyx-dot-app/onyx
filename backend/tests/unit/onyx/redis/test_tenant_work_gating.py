from unittest.mock import patch

import onyx.redis.redis_tenant_work_gating as gating
from onyx.server.runtime.onyx_runtime import OnyxRuntime


def test_single_tenant_activity_does_not_read_redis() -> None:
    with (
        patch.object(gating, "MULTI_TENANT", False),
        patch.object(OnyxRuntime, "get_tenant_work_gating_enabled") as flag,
        patch.object(gating, "get_redis_client") as client,
    ):
        gating.maybe_mark_tenant_active("public", caller="marketplace_sync")
    flag.assert_not_called()
    client.assert_not_called()
