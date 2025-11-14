import contextlib
import secrets
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi_users import exceptions
from fastapi_users.password import PasswordHelper
from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ee.onyx.configs.app_configs import SAML_CONF_DIR
from ee.onyx.db.saml import (
    expire_saml_account,
    get_saml_account,
    upsert_saml_account,
)
from ee.onyx.utils.secrets import (
    compute_sha256_hash,
    extract_hashed_cookie,
)
from onyx.auth.schemas import UserCreate, UserRole
from onyx.auth.users import get_user_manager
from onyx.configs.app_configs import SESSION_EXPIRE_TIME_SECONDS
from onyx.db.auth import get_user_count, get_user_db
from onyx.db.engine import get_async_session, get_session
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter(tags=["SAML-аутентификация"])


async def _find_existing_user(user_manager, email: str) -> User | None:
    """Ищет существующего пользователя по email.

    Args:
        user_manager: Менеджер пользователей
        email: Email для поиска

    Returns:
        Найденный пользователь или None
    """
    try:
        user = await user_manager.get_by_email(email)

        # Проверяем, что пользователь имеет права на веб-логин
        if user.role.is_web_login():
            return user
        else:
            # Если роль не позволяет веб-логин, считаем пользователя несуществующим
            raise exceptions.UserNotExists()

    except exceptions.UserNotExists:
        return None


async def _create_saml_user(user_manager, email: str) -> User:
    """Создает нового пользователя для SAML аутентификации.

    Args:
        user_manager: Менеджер пользователей
        email: Email нового пользователя

    Returns:
        Созданный пользователь
    """
    # Определяем роль:
    # - первый пользователь становится администратором
    # - остальные - обычными
    total_users_count = await get_user_count()
    if total_users_count == 0:
        user_role = UserRole.ADMIN
    else:
        user_role = UserRole.BASIC

    # Генерируем случайный пароль для пользователя
    password_helper = PasswordHelper()
    generated_password = password_helper.generate()
    password_hash = password_helper.hash(generated_password)

    # Создаем пользователя
    new_user = await user_manager.create(
        UserCreate(
            email=email,
            password=password_hash,
            role=user_role,
        )
    )

    return new_user


async def upsert_saml_user(email: str) -> User:
    """Создает или обновляет пользователя на основе SAML аутентификации.

    Если пользователь с указанным email существует и имеет права на веб-логин,
    возвращает существующего пользователя. В противном случае создает нового
    пользователя с автоматически сгенерированным паролем.

    Args:
        email: Email пользователя из SAML провайдера

    Returns:
        Объект пользователя (существующий или вновь созданный)
    """
    logger.debug(f"Попытка создания/обновления SAML пользователя с email: {email}")

    # Создаем контекстные менеджеры для работы с базой данных
    get_async_session_context = contextlib.asynccontextmanager(
        get_async_session
    )  # type:ignore
    get_user_db_context = contextlib.asynccontextmanager(get_user_db)
    get_user_manager_context = contextlib.asynccontextmanager(get_user_manager)

    async with get_async_session_context() as session:
        async with get_user_db_context(session) as user_db:
            async with get_user_manager_context(user_db) as user_manager:

                # Пытаемся найти существующего пользователя
                existing_user = await _find_existing_user(user_manager, email)
                if existing_user:
                    return existing_user

                logger.info("Создание нового пользователя из SAML логина")
                new_user = await _create_saml_user(user_manager, email)
                return new_user


def _get_http_host(request: Request) -> str:
    """Определяет HTTP хост с учетом X-Forwarded заголовков"""

    # Приоритет отдается X-Forwarded-Host для работы за прокси
    forwarded_host = request.headers.get("X-Forwarded-Host")
    if forwarded_host:
        return forwarded_host

    # Fallback на прямой хост клиента
    return request.client.host


def _get_server_port(request: Request) -> str | int:
    """Определяет порт сервера с учетом X-Forwarded заголовков"""

    # Приоритет отдается X-Forwarded-Port для работы за прокси
    forwarded_port = request.headers.get("X-Forwarded-Port")
    if forwarded_port:
        return forwarded_port

    # Fallback на порт из URL
    return request.url.port


async def prepare_from_fastapi_request(request: Request) -> dict[str, Any]:
    """Подготавливает данные запроса для SAML библиотеки OneLogin.

    Преобразует FastAPI request в формат, ожидаемый OneLogin_Saml2_Auth.
    Обрабатывает X-Forwarded заголовки для работы за обратным прокси.

    Args:
        request: FastAPI request объект

    Returns:
        Словарь с параметрами для инициализации SAML аутентификации

    Raises:
        ValueError: Если не удается определить клиентский хост
    """
    # Получаем данные формы из запроса
    form_data = await request.form()

    # Проверяем наличие клиентской информации
    if request.client is None:
        raise ValueError("Некорректный запрос для SAML - отсутствует клиентская информация")

    # Определяем хост и порт с учетом обратного прокси
    http_host = _get_http_host(request)
    server_port = _get_server_port(request)

    # Формируем базовую структуру данных для SAML
    saml_request_data = {
        "http_host": http_host,
        "server_port": server_port,
        "script_name": request.url.path,
        "post_data": {},
        "get_data": {},
    }

    if request.query_params:
        saml_request_data["get_data"] = (request.query_params,)
    if "SAMLResponse" in form_data:
        SAMLResponse = form_data["SAMLResponse"]
        saml_request_data["post_data"]["SAMLResponse"] = SAMLResponse
    if "RelayState" in form_data:
        RelayState = form_data["RelayState"]
        saml_request_data["post_data"]["RelayState"] = RelayState

    return saml_request_data


class SAMLAuthorizeResponse(BaseModel):
    """Ответ с URL для авторизации через SAML провайдера"""

    authorization_url: str = Field(
        description="URL для перенаправления пользователя на страницу аутентификации SAML провайдера"
    )


@router.get(
    "/auth/saml/authorize",
    summary="Инициирует процесс SAML аутентификации",
    response_model=SAMLAuthorizeResponse,
)
async def saml_login(request: Request) -> SAMLAuthorizeResponse:
    """Инициирует процесс SAML аутентификации.

    Генерирует URL для перенаправления пользователя на страницу
    аутентификации SAML провайдера.

    Args:
        request: FastAPI request объект

    Returns:
        Объект с URL для авторизации через SAML
    """
    # Подготавливаем данные запроса для SAML
    saml_request_data = await prepare_from_fastapi_request(request=request)

    # Инициализируем SAML аутентификацию
    saml_auth = OneLogin_Saml2_Auth(
        request_data=saml_request_data,
        custom_base_path=SAML_CONF_DIR,
    )

    # Получаем URL для перенаправления на провайдера
    authorization_url = saml_auth.login()

    logger.debug(f"SAML авторизация: сгенерирован URL {authorization_url}")

    return SAMLAuthorizeResponse(authorization_url=authorization_url)


async def _process_saml_response(request: Request) -> OneLogin_Saml2_Auth:
    """Обрабатывает и валидирует SAML ответ от провайдера"""

    request_data = await prepare_from_fastapi_request(request)
    saml_auth = OneLogin_Saml2_Auth(request_data, custom_base_path=SAML_CONF_DIR)
    saml_auth.process_response()

    errors = saml_auth.get_errors()
    if errors:
        error_msg = (
            f"Ошибки при обработке SAML Response: "
            f"{', '.join(errors)} - {saml_auth.get_last_error_reason()}"
        )
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен. Не удалось обработать SAML Response.",
        )

    if not saml_auth.is_authenticated():
        error_msg = "Доступ запрещен. Пользователь не прошел аутентификацию"
        logger.error(error_msg)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_msg,
        )

    return saml_auth


def _extract_user_email(saml_auth: OneLogin_Saml2_Auth) -> str:
    """Извлекает email пользователя из SAML ответа"""

    email_attributes = saml_auth.get_attribute("email")

    if not email_attributes:
        error_msg = "SAML настроен некорректно, должен быть предоставлен email атрибут."
        logger.error(error_msg)
        raise HTTPException(
            status_code=403,
            detail=error_msg,
        )

    return email_attributes[0]


def _create_session_cookie() -> tuple:
    """Создает сессионную куку и ее хеш"""

    cookie_value = secrets.token_hex(16)
    cookie_hash = compute_sha256_hash(cookie_value)

    return cookie_value, cookie_hash


@router.post(
    "/auth/saml/callback",
    summary="Обработка callback от SAML провайдера после аутентификации",
)
async def saml_login_callback(
    request: Request,
    db_session: Session = Depends(get_session),
) -> Response:
    """Обрабатывает callback от SAML провайдера после аутентификации.

    Валидирует SAML ответ, извлекает email пользователя, создает/обновляет
    учетную запись и устанавливает сессионную куку.

    Args:
        request: FastAPI request объект с SAML ответом
        db_session: Сессия базы данных

    Returns:
        HTTP ответ с установленной сессионной кукой

    Raises:
        HTTPException: При ошибках валидации SAML ответа или аутентификации
    """
    # Обработка и валидация SAML ответа
    saml_auth = await _process_saml_response(request)

    # Извлечение email пользователя из SAML ответа
    user_email = _extract_user_email(saml_auth=saml_auth)

    # Создание или обновление пользователя в системе (upsert = update or insert)
    # Если пользователь существует - возвращает его, если нет - создает нового
    user = await upsert_saml_user(email=user_email)

    # Генерация сессионной куки и ее хеша для безопасного хранения
    cookie_value, cookie_hash = _create_session_cookie()

    # Создание или обновление SAML аккаунта пользователя (upsert = update or insert)
    # Связывает пользователя с сессионной кукой и устанавливает время expiration
    upsert_saml_account(user_id=user.id, cookie=cookie_hash, db_session=db_session)

    # Перенаправляем на главную страницу поиска SmartSearch
    response = Response(status_code=status.HTTP_204_NO_CONTENT)

    response.set_cookie(
        key="session",
        value=cookie_value,
        httponly=True,
        secure=True,
        max_age=SESSION_EXPIRE_TIME_SECONDS,
    )

    return response


@router.post(
    "/auth/saml/logout",
    summary="Выполняет выход из SAML сессии",
)
async def saml_logout(
    request: Request,
    async_db_session: AsyncSession = Depends(get_async_session),
) -> None:
    """Выполняет выход из SAML сессии.

    Удаляет сессионную куку и аннулирует SAML аккаунт в базе данных.

    Args:
        request: FastAPI request объект
        async_db_session: Асинхронная сессия базы данных
    """
    # Извлекаем и проверяем сессионную куку
    session_cookie_hash = extract_hashed_cookie(request=request)

    if not session_cookie_hash:
        logger.warning("Сессионная кука не найдена в запросе")
        return

    # Ищем SAML аккаунт по хешу куки
    user_saml_account = await get_saml_account(
        cookie=session_cookie_hash,
        async_db_session=async_db_session,
    )

    if not user_saml_account:
        logger.warning("SAML аккаунт не найден для указанной куки")
        return

    # Аннулируем SAML аккаунт
    await expire_saml_account(
        saml_account=user_saml_account,
        async_db_session=async_db_session,
    )

    logger.info(f"SAML сессия пользователя {user_saml_account.user_id} завершена")
