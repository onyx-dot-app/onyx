"""Which logo the review pack renders under."""

from unittest.mock import MagicMock, patch

from ee.onyx.server.enterprise_settings.models import EnterpriseSettings
from ee.onyx.server.reporting.usage_report_branding import (
    ReportBranding,
    load_report_branding,
)
from onyx.utils.file import FileWithMimeType

_LOGOTYPE = b"logotype-bytes"
_LOGO = b"logo-bytes"


def _file_store(stored: dict[str, FileWithMimeType]) -> MagicMock:
    store = MagicMock()
    store.get_file_with_mime_type.side_effect = lambda file_id: stored.get(file_id)
    return store


def _load(
    settings: EnterpriseSettings, stored: dict[str, FileWithMimeType]
) -> ReportBranding:
    with patch(
        "ee.onyx.server.reporting.usage_report_branding.load_runtime_settings",
        return_value=settings,
    ):
        return load_report_branding(_file_store(stored))


def test_logotype_wins_over_the_square_mark() -> None:
    branding = _load(
        EnterpriseSettings(
            application_name="Acme", use_custom_logo=True, use_custom_logotype=True
        ),
        {
            "__logotype__": FileWithMimeType(data=_LOGOTYPE, mime_type="image/png"),
            "__logo__": FileWithMimeType(data=_LOGO, mime_type="image/png"),
        },
    )

    assert branding.logo == _LOGOTYPE
    assert branding.application_name == "Acme"


def test_falls_back_to_the_square_mark_when_no_logotype() -> None:
    branding = _load(
        EnterpriseSettings(use_custom_logo=True, use_custom_logotype=True),
        {"__logo__": FileWithMimeType(data=_LOGO, mime_type="image/png")},
    )

    assert branding.logo == _LOGO


def test_an_undrawable_logo_becomes_a_wordmark_not_our_mark() -> None:
    """ReportLab cannot draw SVG. Their own name beats stamping the Onyx mark
    on a report they forward to their leadership."""
    branding = _load(
        EnterpriseSettings(application_name="Acme", use_custom_logotype=True),
        {"__logotype__": FileWithMimeType(data=b"<svg/>", mime_type="image/svg+xml")},
    )

    assert branding.logo is None
    assert branding.application_name == "Acme"


def test_bundled_logo_is_used_when_nothing_is_uploaded() -> None:
    branding = _load(EnterpriseSettings(), {})

    assert branding.logo is not None
    assert branding.logo.startswith(b"\x89PNG")


def test_a_file_store_failure_falls_back_to_the_wordmark() -> None:
    """A configured custom logo we cannot read still must not become our mark."""
    store = MagicMock()
    store.get_file_with_mime_type.side_effect = RuntimeError("object storage down")

    with patch(
        "ee.onyx.server.reporting.usage_report_branding.load_runtime_settings",
        return_value=EnterpriseSettings(
            application_name="Acme", use_custom_logotype=True
        ),
    ):
        branding = load_report_branding(store)

    assert branding.logo is None
