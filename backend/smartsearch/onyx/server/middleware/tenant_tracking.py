import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request, Response

from smartsearch.onyx.auth.users import decode_anonymous_user_jwt_token
from smartsearch.onyx.configs.app_configs import ANONYMOUS_USER_COOKIE_NAME
from onyx.auth.api_key import extract_tenant_from_api_key_header
from onyx.configs.constants import TENANT_ID_COOKIE_NAME
from onyx.db.engine import is_valid_schema_name
from onyx.redis.redis_pool import retrieve_auth_token_data_from_redis
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def add_api_server_tenant_id_middleware(
    app: FastAPI, logger: logging.LoggerAdapter
) -> None:
    """Добавляет middleware для определения идентификатора тенанта в API сервере.

    Middleware извлекает идентификатор тенанта из различных источников запроса
    и устанавливает его в контекстную переменную для использования в обработчиках.

    Args:
        app: Экземпляр FastAPI приложения
        logger: Логгер для записи событий
    """
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Извлекает идентификатор тенанта из запроса и устанавливает контекст.

        Специфичная для API сервера логика определения тенанта из различных источников.

        Args:
            request: Входящий HTTP запрос
            call_next: Функция для вызова следующего обработчика

        Returns:
            Ответ от следующего обработчика

        Raises:
            HTTPException: При ошибках определения тенанта
        """
        try:
            if MULTI_TENANT:
                # Определяем идентификатор тенанта для мультитенантного режима
                tenant_identifier = await _get_tenant_id_from_request(request, logger)
            else:
                # Используем схему по умолчанию для однтенантного режима
                tenant_identifier = POSTGRES_DEFAULT_SCHEMA

            # Устанавливаем идентификатор тенанта в контекстную переменную
            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_identifier)
            return await call_next(request)

        except Exception as error:
            logger.exception(
                "Ошибка в middleware определения тенанта: %s",
                str(error),
            )
            raise


async def _get_tenant_id_from_request(
    request: Request, logger: logging.LoggerAdapter
) -> str:
    """Извлекает идентификатор тенанта из HTTP запроса.

    Проверяет различные источники в порядке приоритета:
    1. Заголовок API ключа
    2. Redis-токен аутентификации (в куках fastapiusersauth)
    3. Кука анонимного пользователя
    4. Явная кука идентификатора тенанта

    Returns:
        Идентификатор тенанта или схема по умолчанию

    Raises:
        HTTPException: При невалидном формате идентификатора тенанта
    """
    tenant_identifier = None

    # Проверяем заголовок API ключа
    tenant_identifier = extract_tenant_from_api_key_header(request)
    if tenant_identifier is not None:
        return tenant_identifier

    try:
        # Получаем данные аутентификационного токена из Redis
        auth_token_data = await retrieve_auth_token_data_from_redis(request)

        if auth_token_data:
            # Извлекаем идентификатор тенанта из payload токена
            tenant_from_token = auth_token_data.get(
                "tenant_id", POSTGRES_DEFAULT_SCHEMA
            )

            if tenant_from_token is not None:
                tenant_identifier = str(tenant_from_token)


            if tenant_identifier and not is_valid_schema_name(tenant_identifier):
                error_message = "Невалидный формат идентификатора тенанта"
                raise HTTPException(status_code=400, detail=error_message)

        # Проверяем куку анонимного пользователя
        anonymous_cookie_value = request.cookies.get(ANONYMOUS_USER_COOKIE_NAME)
        if anonymous_cookie_value:
            try:
                # Декодируем JWT токен анонимного пользователя
                anonymous_user_info = decode_anonymous_user_jwt_token(
                    anonymous_cookie_value
                )
                tenant_identifier = anonymous_user_info.get(
                    "tenant_id", POSTGRES_DEFAULT_SCHEMA
                )

                # Проверяем валидность идентификатора тенанта
                if not tenant_identifier or not is_valid_schema_name(tenant_identifier):
                    error_message = "Невалидный формат идентификатора тенанта"
                    raise HTTPException(status_code=400, detail=error_message)

                return tenant_identifier

            except Exception as decode_error:
                logger.error(
                    "Ошибка декодирования куки анонимного пользователя: %s",
                    str(decode_error),
                )
                # Продолжаем попытки аутентификации

        logger.debug(
            "Данные токена не найдены или истекли в Redis, "
            "используется схема по умолчанию: POSTGRES_DEFAULT_SCHEMA",
        )

        # Возвращаем схему PostgreSQL по умолчанию для неаутентифицированных запросов
        # Контекстная переменная CURRENT_TENANT_ID_CONTEXTVAR инициализируется значением POSTGRES_DEFAULT_SCHEMA,
        # поэтому мы сохраняем консистентность, возвращая его здесь, когда не найден валидный тенант
        return POSTGRES_DEFAULT_SCHEMA

    except Exception as unexpected_error:
        logger.error(
            "Неожиданная ошибка при определении идентификатора тенанта из запроса: %s",
            str(unexpected_error),
        )
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")

    finally:
        # Проверяем, был ли найден идентификатор тенанта в основном блоке try
        if tenant_identifier:
            return tenant_identifier

        # В качестве последней попытки проверяем явную куку с идентификатором тенанта
        explicit_tenant_cookie_value = request.cookies.get(TENANT_ID_COOKIE_NAME)
        if explicit_tenant_cookie_value and is_valid_schema_name(explicit_tenant_cookie_value):
            return explicit_tenant_cookie_value

        # Если достигли этой точки, возвращаем схему по умолчанию
        # Это финальный fallback, когда все другие методы определения тенанта не сработали
        return POSTGRES_DEFAULT_SCHEMA
