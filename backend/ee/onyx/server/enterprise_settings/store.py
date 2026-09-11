import os
from io import BytesIO
from typing import Any, cast

import puremagic
from fastapi import HTTPException, UploadFile

from ee.onyx.server.enterprise_settings.models import (
    APPEARANCE_FIELD_MAX_LENGTHS,
    AnalyticsScriptUpload,
    EnterpriseSettings,
)
from onyx.configs.constants import (
    KV_CUSTOM_ANALYTICS_SCRIPT_KEY,
    KV_ENTERPRISE_SETTINGS_KEY,
    ONYX_DEFAULT_APPLICATION_NAME,
    FileOrigin,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_LOGO_FILENAME = "__logo__"
_LOGOTYPE_FILENAME = "__logotype__"

# The logo is served unauthenticated from the app origin, so only inert raster
# types are stored. An SVG or HTML body would otherwise run as script there.
ALLOWED_LOGO_MIME_TYPES = {"image/png", "image/jpeg"}


def _clamp_appearance_fields(stored: dict[str, Any]) -> dict[str, Any]:
    """Trims stored appearance strings to their caps.

    The caps are `max_length` on the model, so they validate on the way in as
    well as on the way out. A blob written before a cap existed, or under a
    larger one, would otherwise raise on load — and `ee_fetch_settings` is
    unauthenticated, so that is a 500 to every caller and an admin page that
    cannot open to repair the value. Trimming keeps the settings readable and
    leaves the admin looking at what is now stored, rather than at nothing.
    """
    clamped = dict(stored)
    for field, limit in APPEARANCE_FIELD_MAX_LENGTHS.items():
        value = clamped.get(field)
        if isinstance(value, str) and len(value) > limit:
            logger.warning(
                "Enterprise setting %s was %d characters, over its %d limit; "
                "trimming it to load. Re-save the theme settings to keep the "
                "shortened value.",
                field,
                len(value),
                limit,
            )
            clamped[field] = value[:limit]
    return clamped


def load_settings() -> EnterpriseSettings:
    """Loads settings data directly from DB. This should be used primarily
    for checking what is actually in the DB, aka for editing and saving back settings.

    Runtime settings actually used by the application should be checked with
    load_runtime_settings as defaults may be applied at runtime.
    """

    dynamic_config_store = get_kv_store()
    try:
        settings = EnterpriseSettings(
            **_clamp_appearance_fields(
                cast(dict, dynamic_config_store.load(KV_ENTERPRISE_SETTINGS_KEY))
            )
        )
    except KvKeyNotFoundError:
        settings = EnterpriseSettings()
        dynamic_config_store.store(KV_ENTERPRISE_SETTINGS_KEY, settings.model_dump())

    return settings


def store_settings(settings: EnterpriseSettings) -> None:
    """Stores settings directly to the kv store / db."""

    get_kv_store().store(KV_ENTERPRISE_SETTINGS_KEY, settings.model_dump())


def load_runtime_settings() -> EnterpriseSettings:
    """Loads settings from DB and applies any defaults or transformations for use
    at runtime.

    Should not be stored back to the DB.
    """
    enterprise_settings = load_settings()
    if not enterprise_settings.application_name:
        enterprise_settings.application_name = ONYX_DEFAULT_APPLICATION_NAME

    return enterprise_settings


_CUSTOM_ANALYTICS_SECRET_KEY = os.environ.get("CUSTOM_ANALYTICS_SECRET_KEY")


def load_analytics_script() -> str | None:
    dynamic_config_store = get_kv_store()
    try:
        return cast(str, dynamic_config_store.load(KV_CUSTOM_ANALYTICS_SCRIPT_KEY))
    except KvKeyNotFoundError:
        return None


def store_analytics_script(analytics_script_upload: AnalyticsScriptUpload) -> None:
    if (
        not _CUSTOM_ANALYTICS_SECRET_KEY
        or analytics_script_upload.secret_key != _CUSTOM_ANALYTICS_SECRET_KEY
    ):
        raise ValueError("Invalid secret key")

    get_kv_store().store(KV_CUSTOM_ANALYTICS_SCRIPT_KEY, analytics_script_upload.script)


def is_valid_file_type(filename: str) -> bool:
    valid_extensions = (".png", ".jpg", ".jpeg")
    return filename.endswith(valid_extensions)


def sniff_logo_mime_type(data: bytes) -> str | None:
    """The allowed raster type of these bytes, or None if they are not one.

    The filename suffix says nothing about the body, and the file store sniffs
    the served MIME type back out of the bytes, so the content decides.
    """
    try:
        matches = puremagic.magic_string(data)
    except (puremagic.PureError, ValueError):
        # PureError: nothing matched. ValueError: the body is empty.
        return None
    mime_type = matches[0].mime_type if matches else None
    return mime_type if mime_type in ALLOWED_LOGO_MIME_TYPES else None


def upload_logo(file: UploadFile | str, is_logotype: bool = False) -> bool:
    if isinstance(file, str):
        logger.notice("Uploading logo from local path %s", file)
        if not os.path.isfile(file) or not is_valid_file_type(file):
            logger.error(
                "Invalid file type- only .png, .jpg, and .jpeg files are allowed"
            )
            return False

        with open(file, "rb") as file_handle:
            file_content = file_handle.read()
        display_name = file

    else:
        logger.notice("Uploading logo from uploaded file")
        if not file.filename or not is_valid_file_type(file.filename):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type- only .png, .jpg, and .jpeg files are allowed",
            )
        file_content = file.file.read()
        display_name = file.filename

    file_type = sniff_logo_mime_type(file_content)
    if file_type is None:
        if isinstance(file, str):
            logger.error("Logo at %s is not a PNG or JPEG image", file)
            return False
        raise HTTPException(
            status_code=400,
            detail="Invalid file contents- only PNG and JPEG images are allowed",
        )

    file_store = get_default_file_store()
    file_store.save_file(
        content=BytesIO(file_content),
        display_name=display_name,
        file_origin=FileOrigin.OTHER,
        file_type=file_type,
        file_id=_LOGOTYPE_FILENAME if is_logotype else _LOGO_FILENAME,
    )
    return True


def get_logo_filename() -> str:
    return _LOGO_FILENAME


def get_logotype_filename() -> str:
    return _LOGOTYPE_FILENAME
