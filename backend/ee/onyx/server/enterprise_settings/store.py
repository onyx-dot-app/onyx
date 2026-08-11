import os
import re
from io import BytesIO
from typing import IO, Any, cast

import puremagic
from fastapi import UploadFile
from PIL import Image

from ee.onyx.server.enterprise_settings.models import (
    AnalyticsScriptUpload,
    EnterpriseSettings,
)
from onyx.configs.constants import (
    KV_CUSTOM_ANALYTICS_SCRIPT_KEY,
    KV_ENTERPRISE_SETTINGS_KEY,
    ONYX_DEFAULT_APPLICATION_NAME,
    FileOrigin,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_LOGO_FILENAME = "__logo__"
_LOGOTYPE_FILENAME = "__logotype__"


def load_settings() -> EnterpriseSettings:
    """Loads settings data directly from DB. This should be used primarily
    for checking what is actually in the DB, aka for editing and saving back settings.

    Runtime settings actually used by the application should be checked with
    load_runtime_settings as defaults may be applied at runtime.
    """

    dynamic_config_store = get_kv_store()
    try:
        settings = EnterpriseSettings(
            **cast(dict, dynamic_config_store.load(KV_ENTERPRISE_SETTINGS_KEY))
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
    valid_extensions = (".png", ".jpg", ".jpeg", ".svg")
    return filename.lower().endswith(valid_extensions)


# Readers sniff the stored bytes rather than trust the name or the upload
# header, so the upload has to agree with them or a file accepted here is
# stored under a type no reader recognises. SVG is accepted because the web UI
# draws it; the PDF report cannot, and sets the application name as a wordmark
# instead of drawing someone else's mark.
_RASTER_LOGO_TYPES = ("image/png", "image/jpeg")
_SVG_LOGO_TYPE = "image/svg+xml"

# A logo is a wordmark, not an asset library. This bounds what gets buffered
# into memory every time the usage report embeds it.
_MAX_LOGO_BYTES = 5 * 1024 * 1024

_LOGO_TYPE_ERROR = (
    "Invalid file type- only .png, .jpg, .jpeg, and .svg files are allowed. "
    "An SVG renders everywhere except the PDF usage report, which falls back "
    "to your application name."
)

# puremagic misses SVG whenever an exporter emits an XML declaration, a
# doctype, or a leading comment, so the root element is checked directly.
_XML_PROLOGUE = re.compile(
    r"^(?:\s|<\?[^>]*\?>|<!--.*?-->|<!DOCTYPE[^>]*>)+", re.IGNORECASE | re.DOTALL
)


def _is_svg(content: bytes) -> bool:
    head = content[:4096].decode("utf-8", errors="ignore").lstrip("\ufeff").lstrip()
    while True:
        without_prologue = _XML_PROLOGUE.sub("", head, count=1).lstrip()
        if without_prologue == head:
            break
        head = without_prologue
    return head.lower().startswith("<svg")


def sniff_logo_type(content: bytes) -> str | None:
    """The stored bytes' real type, or None when nothing can render it."""
    try:
        matches = puremagic.magic_string(content)
    except Exception:
        matches = []

    for match in matches:
        mime_type = cast(str, match.mime_type)
        if mime_type in _RASTER_LOGO_TYPES:
            try:
                with Image.open(BytesIO(content)) as image:
                    image.verify()
            except Exception:
                return None
            return mime_type

    # SVG has no decode check to run: the web UI draws it and the PDF sets the
    # application name as a wordmark instead.
    return _SVG_LOGO_TYPE if _is_svg(content) else None


def upload_logo(file: UploadFile | str, is_logotype: bool = False) -> bool:
    content: IO[Any]

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

        file_type_or_none = sniff_logo_type(file_content)
        if file_type_or_none is None:
            logger.error(_LOGO_TYPE_ERROR)
            return False
        file_type = file_type_or_none

    else:
        logger.notice("Uploading logo from uploaded file")
        if not file.filename or not is_valid_file_type(file.filename):
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, _LOGO_TYPE_ERROR)

        file_content = file.file.read(_MAX_LOGO_BYTES + 1)
        if len(file_content) > _MAX_LOGO_BYTES:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                f"Logo must be under {_MAX_LOGO_BYTES // (1024 * 1024)} MB.",
            )

        display_name = file.filename

        # An extension is a claim; the bytes are the fact. Readers sniff, so a
        # mislabelled upload would be accepted here and dropped at render time.
        file_type_or_none = sniff_logo_type(file_content)
        if file_type_or_none is None:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, _LOGO_TYPE_ERROR)
        file_type = file_type_or_none

    content = BytesIO(file_content)

    file_store = get_default_file_store()
    file_store.save_file(
        content=content,
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
