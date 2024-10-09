import os
from io import BytesIO
from typing import Any
from typing import cast
from typing import IO

from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.orm import Session

from danswer.configs.constants import FileOrigin
from danswer.configs.constants import KV_CUSTOM_ANALYTICS_SCRIPT_KEY
from danswer.configs.constants import KV_ENTERPRISE_SETTINGS_KEY
from danswer.file_store.file_store import get_default_file_store
from danswer.key_value_store.factory import get_kv_store
from danswer.key_value_store.interface import KvKeyNotFoundError
from danswer.utils.logger import setup_logger
from ee.danswer.server.enterprise_settings.models import AnalyticsScriptUpload
from ee.danswer.server.enterprise_settings.models import EnterpriseSettings


logger = setup_logger()


def load_settings() -> EnterpriseSettings:
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
    get_kv_store().store(KV_ENTERPRISE_SETTINGS_KEY, settings.model_dump())


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


_LOGO_FILENAME = "__logo__"
_LOGOTYPE_FILENAME = "__logotype__"


def is_valid_file_type(filename: str) -> bool:
    valid_extensions = (".png", ".jpg", ".jpeg")
    return filename.endswith(valid_extensions)


def guess_file_type(filename: str) -> str:
    if filename.lower().endswith(".png"):
        return "image/png"
    elif filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def upload_logo(
    db_session: Session, file: UploadFile | str, is_logotype: bool = False
) -> bool:
    content: IO[Any]

    if isinstance(file, str):
        logger.notice(f"Uploading logo from local path {file}")
        if not os.path.isfile(file) or not is_valid_file_type(file):
            logger.error(
                "Invalid file type- only .png, .jpg, and .jpeg files are allowed"
            )
            return False

        with open(file, "rb") as file_handle:
            file_content = file_handle.read()
        content = BytesIO(file_content)
        display_name = file
        file_type = guess_file_type(file)

    else:
        logger.notice("Uploading logo from uploaded file")
        if not file.filename or not is_valid_file_type(file.filename):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type- only .png, .jpg, and .jpeg files are allowed",
            )
        content = file.file
        display_name = file.filename
        file_type = file.content_type or "image/jpeg"

    file_store = get_default_file_store(db_session)
    file_store.save_file(
        file_name=_LOGOTYPE_FILENAME if is_logotype else _LOGO_FILENAME,
        content=content,
        display_name=display_name,
        file_origin=FileOrigin.OTHER,
        file_type=file_type,
    )
    return True
