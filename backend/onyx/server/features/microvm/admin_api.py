"""Admin view of the sandbox runtime: nodes, templates, and whether chats get
sandbox tools. Mounted on every runtime, so admins can see why tools are off.
Single tenant only: the node registry is cluster-wide."""

from fastapi import APIRouter, Depends

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.availability import get_sandbox_status
from onyx.microvm.models import SandboxStatus
from shared_configs.configs import MULTI_TENANT


def _reject_if_multi_tenant() -> None:
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.SINGLE_TENANT_ONLY,
            "Sandbox status is not available on this deployment.",
        )


admin_router = APIRouter(
    prefix="/admin/sandbox",
    dependencies=[
        Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
        Depends(_reject_if_multi_tenant),
    ],
)


@admin_router.get("/status")
def get_admin_sandbox_status(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SandboxStatus:
    return get_sandbox_status()
