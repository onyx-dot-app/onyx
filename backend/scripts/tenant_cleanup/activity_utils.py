from collections.abc import Mapping, Sequence
from datetime import datetime

CRAFT_ACTIVITY_FIELD = "last_craft_activity_time"
ACTIVITY_CSV_FIELDNAMES = (
    "last_query_time",
    CRAFT_ACTIVITY_FIELD,
    "last_activity_time",
    "days_since_last_activity",
)


def _parse_activity_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_last_activity_time(tenant: Mapping[str, object]) -> datetime | None:
    activity_times = [
        activity_time
        for field in ("last_query_time", CRAFT_ACTIVITY_FIELD)
        if (activity_time := _parse_activity_time(tenant.get(field))) is not None
    ]
    return max(activity_times, default=None)


def get_activity_csv_values(
    tenant: Mapping[str, object], now: datetime
) -> dict[str, object]:
    last_activity_time = get_last_activity_time(tenant)
    return {
        "last_query_time": tenant.get("last_query_time") or "Never",
        CRAFT_ACTIVITY_FIELD: tenant.get(CRAFT_ACTIVITY_FIELD) or "Never",
        "last_activity_time": (
            last_activity_time.isoformat()
            if last_activity_time is not None
            else "Never"
        ),
        "days_since_last_activity": (
            str((now - last_activity_time).days)
            if last_activity_time is not None
            else "Never"
        ),
    }


def tenant_data_includes_craft_activity(
    tenants: Sequence[Mapping[str, object]],
) -> bool:
    return all(CRAFT_ACTIVITY_FIELD in tenant for tenant in tenants)
