from datetime import datetime
from datetime import timezone
from typing import Any

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from smartsearch.onyx.server.settings.models import (
    AnalyticsScriptUpload,
    Settings,
)
from smartsearch.onyx.server.settings.store import (
    get_logo_filename,
    get_logotype_filename,
    load_analytics_script,
    load_settings,
    store_analytics_script,
    store_settings,
    upload_logo,
)
from onyx.auth.users import (
    current_admin_user,
    current_user_with_expired_token,
    get_user_manager,
    UserManager,
)
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.file_store.file_store import PostgresBackedFileStore
from onyx.utils.logger import setup_logger

admin_router = APIRouter(tags=["Обновление и загрузка системных настроек"])
basic_router = APIRouter(tags=["Получение системных настроек"])

logger = setup_logger()


class RefreshTokenData(BaseModel):
    """Модель данных для обновления токена аутентификации"""

    access_token: str = Field(
        description="Новый access token для аутентификации"
    )
    refresh_token: str = Field(
        description="Refresh token для будущих операций обновления"
    )
    session: dict = Field(
        ...,
        description="Информация о сессии, включая время истечения токена"
    )
    userinfo: dict = Field(
        ...,
        description="Информация о пользователе: идентификатор и email"
    )

    def __init__(self, **data: Any) -> None:
        """Инициализирует модель с валидацией обязательных полей"""

        super().__init__(**data)

        # Проверяем наличие обязательного поля времени истечения в сессии
        if "exp" not in self.session:
            raise ValueError("Поле 'exp' должно быть указано в словаре сессии")

        # Проверяем наличие обязательных полей в информации о пользователе
        if "userId" not in self.userinfo or "email" not in self.userinfo:
            raise ValueError(
                "Поля 'userId' и 'email' должны быть указаны в словаре userinfo"
            )


@basic_router.post(
    "/settings/refresh-token",
    summary="Обновление access token с помощью refresh token",
)
async def refresh_access_token(
    refresh_token: RefreshTokenData,
    user: User = Depends(current_user_with_expired_token),
    user_manager: UserManager = Depends(get_user_manager),
) -> None:
    """Обновляет access token пользователя с использованием refresh token.

    Эндпоинт для обновления истекшего access token с помощью валидного refresh token.
    Выполняет аутентификацию через внешний OAuth провайдер и обновляет учетные данные
    пользователя в системе.

    Args:
        refresh_token: Данные для обновления токена (access token, refresh token, сессия, userinfo)
        user: Пользователь с истекшим токеном (получается через зависимость)
        user_manager: Менеджер пользователей для обработки OAuth колбэка

    Raises:
        HTTPException: 401 при необходимости полной аутентификации
        HTTPException: 500 при ошибках обновления токена
    """
    try:
        logger.debug(f"Получен ответ от Meechum auth URL для пользователя %s", user.id)

        # Извлекаем новые токены из запроса
        new_access_token = refresh_token.access_token
        new_refresh_token = refresh_token.refresh_token

        # Вычисляем время истечения нового токена
        expiration_timestamp = refresh_token.session["exp"] / 1000
        new_expiry_time = datetime.fromtimestamp(
            expiration_timestamp,
            tz=timezone.utc,
        )
        expires_at_unix = int(new_expiry_time.timestamp())

        logger.debug(f"Access token обновлен для пользователя %s", user.id)

        # Выполняем OAuth колбэк для обновления учетных данных пользователя
        await user_manager.oauth_callback(
            oauth_name="custom",
            access_token=new_access_token,
            account_id=refresh_token.userinfo["userId"],
            account_email=refresh_token.userinfo["email"],
            expires_at=expires_at_unix,
            refresh_token=new_refresh_token,
            associate_by_email=True,
        )

        logger.info(f"Токены успешно обновлены для пользователя %s", user.id)

    except httpx.HTTPStatusError as http_error:
        if http_error.response.status_code == 401:
            logger.warning(f"Требуется полная аутентификация для пользователя %s", user.id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется полная аутентификация",
            )
        logger.error(
            f"HTTP ошибка при обновлении токена для пользователя %s: %s",
            user.id, str(http_error),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось обновить токен",
        )
    except Exception as unexpected_error:
        logger.error(
            f"Неожиданная ошибка при обновлении токена для пользователя %s: %s",
            user.id, str(unexpected_error),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Произошла непредвиденная ошибка",
        )


@admin_router.put(
    "/admin/settings",
    summary="Обновление настроек системы",
)
def put_settings(
    settings: Settings,
    _: User | None = Depends(current_admin_user),
) -> None:
    """Обновляет настройки системы.

    Эндпоинт позволяет администраторам изменять глобальные настройки системы,
    которые сохраняются в ключ-значение хранилище или базе данных.

    Args:
        settings: Новые корпоративные настройки для сохранения
    """
    store_settings(settings)


@basic_router.get(
    "/settings",
    summary="Получение настроек системы",
    response_model=Settings,
)
def fetch_settings() -> Settings:
    """Возвращает текущие настройки системы.

    Эндпоинт предоставляет доступ к настройкам системы, которые включают
    кастомизацию интерфейса, навигации и компонентов чата.

    Returns:
        Текущие корпоративные настройки системы
    """
    return load_settings()


@admin_router.put(
    "/admin/settings/logo",
    summary = "Загрузка логотипа для оформления системы",
)
def put_logo(
    file: UploadFile,
    is_logotype: bool = False,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    """Загружает логотип оформления системы.

    Позволяет администраторам загружать кастомные логотипы для брендирования
    интерфейса системы. Поддерживаются форматы PNG, JPG, JPEG.

    Args:
        file: Файл логотипа для загрузки
        is_logotype: True для загрузки текстового логотипа, False для графического
    """
    upload_logo(file=file, db_session=db_session, is_logotype=is_logotype)


def get_logo_file(db_session: Session) -> Response:
    """Получает файл логотипа системы и возвращает его в виде HTTP ответа.

    Returns:
        Response: HTTP ответ с содержимым логотипа и MIME-типом

    Raises:
        HTTPException: 404 если файл логотипа не найден
    """
    try:
        # Создаем экземпляр файлового хранилища
        file_storage = PostgresBackedFileStore(db_session)

        # Получаем файл логотипа с определением MIME-типа
        logo_filename = get_logo_filename()
        logo_file = file_storage.get_file_with_mime_type(filename=logo_filename)

        # Проверяем что файл был успешно получен
        if not logo_file:
            raise ValueError("Файл логотипа не найден в хранилище")

    except Exception as error:
        # Логируем ошибку и возвращаем HTTP исключение
        logger.error(f"Ошибка при получении логотипа: %s", str(error))
        raise HTTPException(
            status_code=404,
            detail="Файл логотипа не найден",
        )
    else:
        response = Response(content=logo_file.data, media_type=logo_file.mime_type)
        return response


def get_logotype_file(db_session: Session) -> Response:
    """Получает файл текстового логотипа системы и возвращает его в виде HTTP ответа.

    Returns:
        Response: HTTP ответ с содержимым текстового логотипа и MIME-типом

    Raises:
        HTTPException: 404 если файл текстового логотипа не найден
    """
    try:
        # Создаем экземпляр файлового хранилища
        file_storage = PostgresBackedFileStore(db_session)

        # Получаем файл текстового логотипа с определением MIME-типа
        logotype_filename = get_logotype_filename()
        logotype_file = file_storage.get_file_with_mime_type(filename=logotype_filename)

        # Проверяем что файл был успешно получен
        if not logotype_file:
            raise ValueError("Файл текстового логотипа не найден в хранилище")

    except Exception as error:
        # Логируем ошибку и возвращаем HTTP исключение
        logger.error(
            f"Ошибка при получении текстового логотипа: %s",
            str(error)
        )
        raise HTTPException(
            status_code=404,
            detail="Файл текстового логотипа не найден",
        )
    else:
        response = Response(content=logotype_file.data, media_type=logotype_file.mime_type)
        return response


@basic_router.get(
    "/settings/logotype",
    summary="Получение текстового логотипа системы",
)
def fetch_logotype(db_session: Session = Depends(get_session)) -> Response:
    """Возвращает файл текстового логотипа системы для корпоративного оформления.

    Returns:
        Response: HTTP ответ с содержимым текстового логотипа
    """
    return get_logotype_file(db_session)


@basic_router.get(
    "/settings/logo",
    summary="Получение логотипа системы",
)
def fetch_logo(
    is_logotype: bool = False,
    db_session: Session = Depends(get_session),
) -> Response:
    """Возвращает файл логотипа или текстового логотипа системы.

    Поддерживает получение как графического логотипа, так и текстового варианта
    в зависимости от параметра запроса.

    Args:
        is_logotype: Если True - возвращает текстовый логотип, иначе графический

    Returns:
        Response: HTTP ответ с содержимым запрошенного логотипа
    """
    if is_logotype:
        return get_logotype_file(db_session)
    else:
        return get_logo_file(db_session)


@admin_router.put(
    "/admin/settings/custom-analytics-script",
    summary="Загрузка кастомного аналитического скрипта",
)
def upload_custom_analytics_script(
    script_upload: AnalyticsScriptUpload,
    _: User | None = Depends(current_admin_user),
) -> None:
    """Загружает и сохраняет кастомный аналитический скрипт для системы.

    Позволяет администраторам загружать пользовательские скрипты аналитики
    с проверкой секретного ключа для обеспечения безопасности.

    Args:
        script_upload: Данные скрипта аналитики с секретным ключом

    Raises:
        HTTPException: 400 при неверном секретном ключе
    """
    try:
        store_analytics_script(script_upload)
    except ValueError as validation_error:
        raise HTTPException(status_code=400, detail=str(validation_error))


@basic_router.get(
    "/settings/custom-analytics-script",
    summary="Получение кастомного аналитического скрипта",
)
def fetch_custom_analytics_script() -> str | None:
    """Возвращает сохраненный кастомный аналитический скрипт системы.

    Эндпоинт предоставляет доступ к пользовательскому скрипту аналитики,
    который был ранее загружен администратором системы.

    Returns:
        Текст аналитического скрипта или None если скрипт не настроен
    """
    return load_analytics_script()
