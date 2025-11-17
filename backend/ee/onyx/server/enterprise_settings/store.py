import os
from io import BytesIO
from typing import Any
from typing import cast
from typing import IO

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from ee.onyx.server.enterprise_settings.models import (
    AnalyticsScriptUpload,
    EnterpriseSettings,
)
from onyx.configs.constants import (
    FileOrigin,
    KV_CUSTOM_ANALYTICS_SCRIPT_KEY,
    KV_ENTERPRISE_SETTINGS_KEY,
    ONYX_DEFAULT_APPLICATION_NAME,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger


logger = setup_logger()

_LOGO_FILENAME = "__logo__"
_LOGOTYPE_FILENAME = "__logotype__"


def load_settings() -> EnterpriseSettings:
    """Загружает настройки системы напрямую из базы данных.

    Основное назначение - получение точных настроек, хранящихся в БД,
    для последующего редактирования и сохранения. Для получения настроек,
    используемых в runtime, следует использовать load_runtime_settings,
    так как в runtime могут применяться значения по умолчанию.

    Returns:
        EnterpriseSettings: Настройки предприятия из базы данных или пустые настройки по умолчанию
    """

    # Получаем хранилище ключ-значение для доступа к настройкам
    config_store = get_kv_store()

    try:
        # Пытаемся загрузить настройки из хранилища
        stored_settings_data = config_store.load(KV_ENTERPRISE_SETTINGS_KEY)
        settings_dict = cast(dict, stored_settings_data)

        # Создаем объект настроек из данных хранилища
        enterprise_settings = EnterpriseSettings(**settings_dict)

    except KvKeyNotFoundError:
        # Если настройки не найдены, создаем объект с настройками по умолчанию
        enterprise_settings = EnterpriseSettings()

        # Сохраняем настройки по умолчанию в хранилище
        default_settings_data = enterprise_settings.model_dump()
        config_store.store(KV_ENTERPRISE_SETTINGS_KEY, default_settings_data)

    return enterprise_settings


def store_settings(settings: EnterpriseSettings) -> None:
    """Сохраняет настройки напрямую в ключ-значение хранилище или базу данных.

    Args:
        settings: Объект настроек предприятия для сохранения
    """
    # Получаем экземпляр ключ-значение хранилища
    key_value_store = get_kv_store()

    # Преобразуем настройки в словарь и сохраняем
    settings_data = settings.model_dump()
    key_value_store.store(KV_ENTERPRISE_SETTINGS_KEY, settings_data)


def load_runtime_settings() -> EnterpriseSettings:
    """Загружает настройки из БД и применяет значения по умолчанию для использования в runtime.

    Выполняет преобразования и устанавливает значения по умолчанию для полей,
    которые не были заданы в сохраненных настройках. Полученные настройки
    не должны сохраняться обратно в базу данных.

    Returns:
        EnterpriseSettings: Настройки предприятия с примененными значениями по умолчанию
    """
    # Загружаем настройки из базы данных
    enterprise_settings = load_settings()

    # Применяем значение по умолчанию для названия приложения, если оно не задано
    if not enterprise_settings.application_name:
        enterprise_settings.application_name = ONYX_DEFAULT_APPLICATION_NAME

    return enterprise_settings


_CUSTOM_ANALYTICS_SECRET_KEY = os.environ.get("CUSTOM_ANALYTICS_SECRET_KEY")


def load_analytics_script() -> str | None:
    """Загружает кастомный аналитический скрипт из хранилища.

    Returns:
        Текст аналитического скрипта или None если скрипт не найден
    """
    # Получаем хранилище ключ-значение
    config_store = get_kv_store()

    try:
        # Пытаемся загрузить скрипт из хранилища
        script_content = config_store.load(KV_CUSTOM_ANALYTICS_SCRIPT_KEY)
        return cast(str, script_content)
    except KvKeyNotFoundError:
        # Если скрипт не найден, возвращаем None
        return None


def store_analytics_script(analytics_script_upload: AnalyticsScriptUpload) -> None:
    """Сохраняет кастомный аналитический скрипт с проверкой секретного ключа.

    Args:
        analytics_script_upload: Данные для загрузки скрипта аналитики

    Raises:
        ValueError: При неверном секретном ключе
    """
    # Проверяем что секретный ключ настроен в системе
    if not _CUSTOM_ANALYTICS_SECRET_KEY:
        raise ValueError("Секретный ключ аналитики не настроен в системе")

    # Проверяем соответствие переданного ключа системному
    if analytics_script_upload.secret_key != _CUSTOM_ANALYTICS_SECRET_KEY:
        raise ValueError("Неверный секретный ключ")

    # Получаем хранилище и сохраняем скрипт
    config_store = get_kv_store()
    config_store.store(KV_CUSTOM_ANALYTICS_SCRIPT_KEY, analytics_script_upload.script)


def is_valid_file_type(filename: str) -> bool:
    """Проверяет что файл имеет допустимый тип для загрузки как логотип.

    Args:
        filename: Имя файла для проверки

    Returns:
        True если файл имеет допустимое расширение
    """

    valid_extensions = (".png", ".jpg", ".jpeg")
    return filename.endswith(valid_extensions)


def guess_file_type(filename: str) -> str:
    """Определяет MIME-тип файла на основе его расширения.

    Args:
        filename: Имя файла для определения типа

    Returns:
        Строка с MIME-типом файла
    """
    lowercase_filename = filename.lower()

    if lowercase_filename.endswith(".png"):
        return "image/png"
    elif lowercase_filename.endswith(".jpg") or lowercase_filename.endswith(".jpeg"):
        return "image/jpeg"
    else:
        return "application/octet-stream"


def upload_logo(
    db_session: Session,
    file: UploadFile | str,
    is_logotype: bool = False,
) -> bool:
    """Загружает логотип или текстовый логотип в систему.

    Args:
        file: Файл для загрузки (объект UploadFile или путь к файлу)
        is_logotype: True для загрузки текстового логотипа

    Returns:
        True если загрузка прошла успешно

    Raises:
        HTTPException: 400 при неверном формате файла
    """
    file_content_stream: IO[Any]
    file_display_name: str
    detected_file_type: str

    # Обработка загрузки из локального файла
    if isinstance(file, str):
        logger.notice(f"Загрузка логотипа из локального пути: {file}")

        # Проверяем что файл существует и имеет допустимый тип
        if not os.path.isfile(file) or not is_valid_file_type(file):
            logger.error("Неверный тип файла - допускаются только .png, .jpg и .jpeg файлы")
            return False

        # Читаем содержимое файла
        with open(file, "rb") as file_handle:
            file_data = file_handle.read()

        file_content_stream = BytesIO(file_data)
        file_display_name = file
        detected_file_type = guess_file_type(file)

    # Обработка загрузки через UploadFile
    else:
        logger.notice("Загрузка логотипа из загруженного файла")

        # Проверяем имя файла и его тип
        if not file.filename or not is_valid_file_type(file.filename):
            raise HTTPException(
                status_code=400,
                detail="Неверный тип файла - допускаются только .png, .jpg и .jpeg файлы",
            )

        file_content_stream = file.file
        file_display_name = file.filename
        detected_file_type = file.content_type or "image/jpeg"

    # Определяем имя файла в зависимости от типа логотипа
    target_filename = _LOGOTYPE_FILENAME if is_logotype else _LOGO_FILENAME

    # Сохраняем файл в хранилище
    file_storage = get_default_file_store(db_session)
    file_storage.save_file(
        file_name=target_filename,
        content=file_content_stream,
        display_name=file_display_name,
        file_origin=FileOrigin.OTHER,
        file_type=detected_file_type,
    )

    return True


def get_logo_filename() -> str:
    """Возвращает имя файла для графического логотипа.

    Returns:
        Имя файла логотипа в хранилище
    """
    return _LOGO_FILENAME


def get_logotype_filename() -> str:
    """Возвращает имя файла для текстового логотипа.

    Returns:
        Имя файла текстового логотипа в хранилище
    """
    return _LOGOTYPE_FILENAME
