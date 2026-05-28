"""Prometheus collector for self-hosted license seat usage and expiry.

Self-hosted only. Cloud tracks seats via Stripe subscriptions, not licenses, so
this collector no-ops when ``MULTI_TENANT`` is set. Registered on the API
server's default registry from ``main.py`` lifespan and exposed via ``/metrics``,
letting operators alert on seat exhaustion and upcoming expiry in their own
Prometheus/Alertmanager.

Read at scrape time (the Collector pattern) so seat counts and expiry are fresh.
Emits nothing when no license is installed — an absent series rather than zeros,
so unlicensed instances don't trip "0 seats remaining" alerts.
"""

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY

from ee.onyx.db.license import get_license_metadata
from ee.onyx.db.license import get_used_seats
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.server.metrics.indexing_pipeline import _CachedCollector
from onyx.server.settings.models import ApplicationStatus
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()


class LicenseMetricsCollector(_CachedCollector):
    """Emits license seat and expiry gauges, read from the license at scrape time."""

    def _collect_fresh(self) -> list[GaugeMetricFamily]:
        if MULTI_TENANT:
            return []

        with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
            metadata = get_license_metadata(
                db_session, tenant_id=POSTGRES_DEFAULT_SCHEMA
            )
            if metadata is None:
                return []
            used_seats = get_used_seats(POSTGRES_DEFAULT_SCHEMA)

        total_seats = metadata.seats
        available_seats = max(0, total_seats - used_seats)

        seats_total = GaugeMetricFamily(
            "onyx_license_seats_total",
            "Total seats granted by the installed license",
        )
        seats_total.add_metric([], total_seats)

        seats_used = GaugeMetricFamily(
            "onyx_license_seats_used",
            "Seats currently consumed by active users",
        )
        seats_used.add_metric([], used_seats)

        seats_available = GaugeMetricFamily(
            "onyx_license_seats_available",
            "Seats remaining before the license limit is reached",
        )
        seats_available.add_metric([], available_seats)

        expires = GaugeMetricFamily(
            "onyx_license_expires_timestamp_seconds",
            "Unix timestamp when the installed license expires",
        )
        expires.add_metric([], metadata.expires_at.timestamp())

        # Mirror the license-enforcement middleware's two block conditions:
        # fully-expired (GATED_ACCESS) or seat limit exceeded (used > total).
        # Status alone never carries SEAT_LIMIT_EXCEEDED, so the seat check is
        # explicit here.
        access_blocked = (
            metadata.status == ApplicationStatus.GATED_ACCESS
            or used_seats > total_seats
        )
        active = GaugeMetricFamily(
            "onyx_license_active",
            "License access status (1=ok, 0=blocked: expired/gated or seat limit exceeded)",
        )
        active.add_metric([], 0.0 if access_blocked else 1.0)

        return [seats_total, seats_used, seats_available, expires, active]


_license_collector = LicenseMetricsCollector()


def register_license_metrics() -> None:
    """Register the license metrics collector on the default Prometheus registry.

    Called from the API server lifespan via ``fetch_ee_implementation_or_noop``,
    so community builds skip it entirely.
    """
    try:
        REGISTRY.register(_license_collector)
    except ValueError:
        logger.debug("License metrics collector already registered")
