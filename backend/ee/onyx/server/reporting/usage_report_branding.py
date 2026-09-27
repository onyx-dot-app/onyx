"""Branding for the usage report review pack, from enterprise settings."""

from pathlib import Path

from pydantic import BaseModel

from ee.onyx.server.enterprise_settings.store import (
    get_logo_filename,
    get_logotype_filename,
    load_runtime_settings,
)
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME
from onyx.file_store.file_store import FileStore
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FALLBACK_LOGO = Path(__file__).parents[4] / "static" / "images" / "logotype.png"

_SUPPORTED_LOGO_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/gif")


class ReportBranding(BaseModel):
    application_name: str
    # Raster bytes ReportLab can draw. None means the pack sets the name as a
    # wordmark instead, which is right when a deployment has a custom logo we
    # cannot draw: its own name beats another company's mark.
    logo: bytes | None = None


def _read_logo(file_store: FileStore, file_id: str) -> bytes | None:
    try:
        stored = file_store.get_file_with_mime_type(file_id)
    except Exception:
        logger.exception("Failed to read logo %s for the usage report", file_id)
        return None

    if stored is None:
        return None

    # ReportLab cannot rasterize SVG, the common upload.
    if stored.mime_type not in _SUPPORTED_LOGO_TYPES:
        logger.info(
            "Usage report cannot draw logo %s of type %s", file_id, stored.mime_type
        )
        return None

    return stored.data


def load_report_branding(file_store: FileStore) -> ReportBranding:
    settings = load_runtime_settings()
    name = settings.application_name or ONYX_DEFAULT_APPLICATION_NAME

    has_custom_logo = settings.use_custom_logotype or settings.use_custom_logo
    logo: bytes | None = None
    if settings.use_custom_logotype:
        logo = _read_logo(file_store, get_logotype_filename())
    if logo is None and settings.use_custom_logo:
        logo = _read_logo(file_store, get_logo_filename())

    if logo is None and has_custom_logo:
        # Their logo exists but cannot be drawn, so fall through to the
        # wordmark. Stamping the bundled mark here would ship our brand on
        # their report.
        logger.warning(
            "Usage report rendering %s as a wordmark: the configured logo is "
            "not a raster image ReportLab can draw",
            name,
        )
        return ReportBranding(application_name=name, logo=None)

    if logo is None:
        try:
            logo = _FALLBACK_LOGO.read_bytes()
        except OSError:
            logger.exception("Usage report could not read the fallback logo")

    return ReportBranding(application_name=name, logo=logo)
