from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ee.onyx.server.security.models import AuditClassStatus, AuditStreamStatus
from ee.onyx.utils.audit import OCSFEventClass, audit_enabled_for_tenant
from ee.onyx.utils.audit_stats import read_class_stats
from ee.onyx.utils.credential_audit import CREDENTIAL_ACCESS_STATS_CLASS
from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.security.store import get_security_settings
from shared_configs.configs import LOG_FORMAT
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/admin/security")

_STATUS_CLASSES: tuple[str, ...] = (
    *(event_class.value for event_class in OCSFEventClass),
    CREDENTIAL_ACCESS_STATS_CLASS,
)


@router.get("/audit-status")
def get_audit_stream_status(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> AuditStreamStatus:
    tenant_id = get_current_tenant_id()
    settings = get_security_settings()
    classes: list[AuditClassStatus] = []
    for event_class in _STATUS_CLASSES:
        count, last_event_ts = read_class_stats(tenant_id, event_class)
        classes.append(
            AuditClassStatus(
                event_class=event_class,
                events_last_24h=count,
                last_event_at=(
                    datetime.fromtimestamp(last_event_ts, tz=timezone.utc)
                    if last_event_ts is not None
                    else None
                ),
            )
        )
    return AuditStreamStatus(
        enabled=audit_enabled_for_tenant(tenant_id),
        log_format=LOG_FORMAT,
        categories=list(settings.audit_event_categories),
        include_query_text=settings.audit_include_query_text,
        classes=classes,
    )
