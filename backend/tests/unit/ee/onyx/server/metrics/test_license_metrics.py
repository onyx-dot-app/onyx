"""Tests for the self-hosted license Prometheus collector."""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from prometheus_client.core import GaugeMetricFamily

from ee.onyx.server.metrics.license_metrics import LicenseMetricsCollector
from onyx.server.settings.models import ApplicationStatus

_EXPIRES_AT = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _values(families: list[GaugeMetricFamily]) -> dict[str, float]:
    return {f.name: f.samples[0].value for f in families}


def _metadata(seats: int, status: ApplicationStatus) -> MagicMock:
    metadata = MagicMock()
    metadata.seats = seats
    metadata.status = status
    metadata.expires_at = _EXPIRES_AT
    return metadata


class TestLicenseMetricsCollector:
    def test_emits_seat_and_expiry_gauges(self) -> None:
        collector = LicenseMetricsCollector(cache_ttl=0)
        with (
            patch("ee.onyx.server.metrics.license_metrics.MULTI_TENANT", False),
            patch("ee.onyx.server.metrics.license_metrics.get_session_with_tenant"),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_license_metadata",
                return_value=_metadata(10, ApplicationStatus.ACTIVE),
            ),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_used_seats",
                return_value=7,
            ),
        ):
            values = _values(collector.collect())

        assert values["onyx_license_seats_total"] == 10
        assert values["onyx_license_seats_used"] == 7
        assert values["onyx_license_seats_available"] == 3
        assert values["onyx_license_expires_timestamp_seconds"] == (
            _EXPIRES_AT.timestamp()
        )
        assert values["onyx_license_active"] == 1.0

    def test_active_one_during_grace_period(self) -> None:
        collector = LicenseMetricsCollector(cache_ttl=0)
        with (
            patch("ee.onyx.server.metrics.license_metrics.MULTI_TENANT", False),
            patch("ee.onyx.server.metrics.license_metrics.get_session_with_tenant"),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_license_metadata",
                return_value=_metadata(10, ApplicationStatus.GRACE_PERIOD),
            ),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_used_seats",
                return_value=9,
            ),
        ):
            values = _values(collector.collect())

        assert values["onyx_license_active"] == 1.0
        assert values["onyx_license_seats_available"] == 1

    def test_active_zero_when_gated(self) -> None:
        collector = LicenseMetricsCollector(cache_ttl=0)
        with (
            patch("ee.onyx.server.metrics.license_metrics.MULTI_TENANT", False),
            patch("ee.onyx.server.metrics.license_metrics.get_session_with_tenant"),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_license_metadata",
                return_value=_metadata(5, ApplicationStatus.GATED_ACCESS),
            ),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_used_seats",
                return_value=5,
            ),
        ):
            values = _values(collector.collect())

        assert values["onyx_license_active"] == 0.0
        assert values["onyx_license_seats_available"] == 0

    def test_active_zero_when_seat_limit_exceeded(self) -> None:
        # ACTIVE license but used > seats — the enforcement middleware 402-blocks
        # this, so active must read 0 even though status is not GATED_ACCESS.
        collector = LicenseMetricsCollector(cache_ttl=0)
        with (
            patch("ee.onyx.server.metrics.license_metrics.MULTI_TENANT", False),
            patch("ee.onyx.server.metrics.license_metrics.get_session_with_tenant"),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_license_metadata",
                return_value=_metadata(5, ApplicationStatus.ACTIVE),
            ),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_used_seats",
                return_value=8,
            ),
        ):
            values = _values(collector.collect())

        assert values["onyx_license_active"] == 0.0
        assert values["onyx_license_seats_available"] == 0

    def test_empty_when_multi_tenant(self) -> None:
        collector = LicenseMetricsCollector(cache_ttl=0)
        with patch("ee.onyx.server.metrics.license_metrics.MULTI_TENANT", True):
            assert collector.collect() == []

    def test_empty_when_no_license(self) -> None:
        collector = LicenseMetricsCollector(cache_ttl=0)
        with (
            patch("ee.onyx.server.metrics.license_metrics.MULTI_TENANT", False),
            patch("ee.onyx.server.metrics.license_metrics.get_session_with_tenant"),
            patch(
                "ee.onyx.server.metrics.license_metrics.get_license_metadata",
                return_value=None,
            ),
        ):
            assert collector.collect() == []
