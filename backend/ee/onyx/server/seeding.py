import json
import os
from copy import deepcopy
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ee.onyx.db.standard_answer import (
    create_initial_default_standard_answer_category,
)
from ee.onyx.server.enterprise_settings.models import (
    AnalyticsScriptUpload,
    EnterpriseSettings,
    NavigationItem,
)
from ee.onyx.server.enterprise_settings.store import (
    store_analytics_script,
    store_settings as store_ee_settings,
)
from ee.onyx.server.enterprise_settings.store import upload_logo
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.engine import get_session_context_manager
from onyx.db.llm import update_default_provider, upsert_llm_provider
from onyx.db.models import Tool
from onyx.db.persona import upsert_persona
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.settings.models import Settings
from onyx.server.settings.store import store_settings as store_base_settings
from onyx.utils.logger import setup_logger


class CustomToolSeed(BaseModel):
    """Конфигурация кастомного инструмента для инициализации системы.

    Определяет параметры пользовательского инструмента, который будет
    создан при инициализации системы из файла OpenAPI спецификации.
    """

    name: str = Field(
        description="Уникальное имя инструмента в системе",
    )
    description: str = Field(
        description="Описание инструмента и его функциональности",
    )
    definition_path: str = Field(
        description="Путь к файлу с OpenAPI спецификацией инструмента",
    )
    custom_headers: Optional[list[dict]] = Field(
        default=None,
        description="Дополнительные HTTP заголовки для запросов инструмента",
    )
    display_name: Optional[str] = Field(
        default=None,
        description="Отображаемое имя инструмента в интерфейсе",
    )
    in_code_tool_id: Optional[str] = Field(
        default=None,
        description="Идентификатор инструмента в коде системы",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Идентификатор пользователя-владельца инструмента",
    )

logger = setup_logger()

_SEED_CONFIG_ENV_VAR_NAME = "ENV_SEED_CONFIGURATION"


class NavigationItemSeed(BaseModel):
    """Конфигурация элемента навигации для инициализации системы"""

    link: str = Field(
        description="URL ссылка для элемента навигации",
    )
    title: str = Field(
        description="Заголовок элемента навигации для отображения в меню",
    )
    svg_path: str = Field(
        description="Путь к файлу SVG логотипа. ВНИМАНИЕ: SVG не должен содержать атрибуты width/height",
    )


class SeedConfiguration(BaseModel):
    """Конфигурация для инициализации системы.

    Содержит все необходимые параметры для первоначальной настройки системы,
    включая языковые модели, ассистентов, настройки и кастомные компоненты.
    """

    llms: list[LLMProviderUpsertRequest] | None = Field(
        default=None,
        description="Список провайдеров языковых моделей для загрузки в систему",
    )
    admin_user_emails: list[str] | None = Field(
        default=None,
        description="Список email адресов пользователей с правами администратора",
    )
    seeded_logo_path: str | None = Field(
        default=None,
        description="Путь к файлу логотипа для загрузки в систему",
    )
    personas: list[PersonaUpsertRequest] | None = Field(
        default=None,
        description="Список ассистентов для создания в системе",
    )
    settings: Settings | None = Field(
        default=None,
        description="Базовые настройки системы",
    )
    enterprise_settings: EnterpriseSettings | None = Field(
        default=None,
        description="Системные настройки системы",
    )

    nav_item_overrides: list[NavigationItemSeed] | None = Field(
        default=None,
        description="Кастомные элементы навигации с пользовательскими SVG логотипами",
    )

    analytics_script_path: str | None = Field(
        default=None,
        description="Путь к файлу аналитического скрипта для загрузки в систему",
    )
    custom_tools: list[CustomToolSeed] | None = Field(
        default=None,
        description="Список кастомных инструментов для создания в системе",
    )


def _parse_env() -> SeedConfiguration | None:
    """Парсит конфигурацию инициализации из переменной окружения.

    Читает JSON конфигурацию из переменной окружения и преобразует ее
    в объект SeedConfiguration.

    Returns:
        Конфигурация инициализации или None, если переменная не задана
    """
    config_env_variable = os.getenv(_SEED_CONFIG_ENV_VAR_NAME)

    # Если переменная окружения не задана - возвращаем None
    if not config_env_variable:
        return None

    try:
        # Парсим JSON конфигурацию из переменной окружения
        seed_config = SeedConfiguration.model_validate_json(config_env_variable)
        return seed_config

    except Exception as error:
        logger.error("Ошибка при парсинге конфигурации инициализации: %s", str(error))
        return None


def _seed_custom_tools(
    db_session: Session,
    tools: list[CustomToolSeed],
) -> None:
    """Загружает кастомные инструменты в базу данных из файлов определений.

    Читает OpenAPI схемы из файлов и создает соответствующие записи инструментов в БД.
    Обрабатывает ошибки чтения файлов и парсинга JSON для каждого инструмента отдельно.

    Args:
        tools: Список инструментов для загрузки в систему
    """
    if not tools:
        return

    logger.notice("Начало загрузки кастомных инструментов")
    successful_tools_count = 0

    for tool_seed in tools:
        try:
            logger.debug(f"Попытка загрузки инструмента: %s", tool_seed.name)
            logger.debug(f"Чтение определения из: %s", tool_seed.definition_path)

            # Читаем содержимое файла определения
            with open(tool_seed.definition_path, "r") as definition_file:
                file_content = definition_file.read()

                # Проверяем что файл не пустой
                if not file_content.strip():
                    raise ValueError("Файл определения пуст")

                # Парсим JSON схему
                openapi_schema = json.loads(file_content)

            # Создаем объект инструмента для базы данных
            database_tool = Tool(
                name=tool_seed.name,
                description=tool_seed.description,
                openapi_schema=openapi_schema,
                custom_headers=tool_seed.custom_headers,
                display_name=tool_seed.display_name,
                in_code_tool_id=tool_seed.in_code_tool_id,
                user_id=tool_seed.user_id,
            )

            # Добавляем инструмент в сессию
            db_session.add(database_tool)
            successful_tools_count += 1
            logger.debug(f"Успешно добавлен инструмент: %s", tool_seed.name)

        except FileNotFoundError:
            logger.error(
                f"Файл определения не найден для инструмента %s: %s",
                tool_seed.name, tool_seed.definition_path,
            )
        except json.JSONDecodeError as json_error:
            logger.error(
                f"Невалидный JSON в файле определения для инструмента %s: %s",
                tool_seed.name, str(json_error),
            )
        except Exception as unexpected_error:
            logger.error(
                f"Ошибка при загрузке инструмента %s: %s",
                tool_seed.name, str(unexpected_error),
            )


    # Сохраняем все успешно обработанные инструменты в БД
    if successful_tools_count > 0:
        db_session.commit()
        logger.notice(f"Успешно загружено %s кастомных инструментов", successful_tools_count)
    else:
        logger.warning("Не удалось загрузить ни одного инструмента")


def _seed_llms(
    db_session: Session,
    llm_upsert_requests: list[LLMProviderUpsertRequest],
) -> None:
    """Загружает провайдеров языковых моделей в базу данных.

    Создает или обновляет провайдеров LLM в системе и устанавливает первого
    провайдера в списке как провайдера по умолчанию.

    Args:
        llm_upsert_requests: Список провайдеров LLM для загрузки
    """
    if not llm_upsert_requests:
        return

    logger.notice("Начало загрузки провайдеров языковых моделей")

    # Создаем или обновляем всех провайдеров
    created_providers = []
    for provider_request in llm_upsert_requests:
        try:
            provider = upsert_llm_provider(provider_request, db_session)
            created_providers.append(provider)
            logger.debug("Успешно обработан провайдер: %s", provider_request.provider)
        except Exception as error:
            logger.error("Ошибка при загрузке провайдера %s: %s", provider_request.provider, str(error))

    # Устанавливаем первого провайдера как провайдера по умолчанию
    if created_providers:
        first_provider = created_providers[0]
        update_default_provider(provider_id=first_provider.id, db_session=db_session)
        logger.notice("Установлен провайдер по умолчанию: %s", first_provider.provider)

    logger.notice("Завершена загрузка %d провайдеров LLM", len(created_providers))


def _seed_personas(
    db_session: Session,
    personas: list[PersonaUpsertRequest],
) -> None:
    """Загружает ассистентов в базу данных.

    Создает или обновляет ассистентов в системе с проверкой наличия обязательных промптов.

    Args:
        personas: Список ассистентов для загрузки в систему

    Raises:
        ValueError: Если у ассистента не указаны промпты
    """
    if not personas:
        return

    logger.notice("Начало загрузки ассистентов")

    for persona_request in personas:
        # Проверяем что у ассистента есть промпты
        if not persona_request.prompt_ids:
            error_message = f"Невалидный ассистент с именем {persona_request.name}: отсутствуют промпты"
            raise ValueError(error_message)

        try:
            num_chunks = 0.0
            if persona_request.num_chunks is not None:
                num_chunks = persona_request.num_chunks

            # Создаем или обновляем ассистента
            upsert_persona(
                user=None,  # Загрузка выполняется от имени администратора
                name=persona_request.name,
                description=persona_request.description,
                num_chunks=num_chunks,
                llm_relevance_filter=persona_request.llm_relevance_filter,
                llm_filter_extraction=persona_request.llm_filter_extraction,
                recency_bias=RecencyBiasSetting.AUTO,
                prompt_ids=persona_request.prompt_ids,
                document_set_ids=persona_request.document_set_ids,
                llm_model_provider_override=persona_request.llm_model_provider_override,
                llm_model_version_override=persona_request.llm_model_version_override,
                starter_messages=persona_request.starter_messages,
                is_public=persona_request.is_public,
                db_session=db_session,
                tool_ids=persona_request.tool_ids,
                display_priority=persona_request.display_priority,
            )
            logger.debug("Успешно обработан ассистент: %s", persona_request.name)

        except Exception as error:
            logger.error(
                "Ошибка при загрузке ассистента %s: %s",
                persona_request.name, str(error),
            )

    logger.notice("Завершена загрузка %d ассистентов", len(personas))


def _seed_settings(settings: Settings) -> None:
    """Загружает базовые настройки системы.

    Сохраняет начальные настройки системы в хранилище конфигурации.

    Args:
        settings: Объект настроек для загрузки в систему
    """
    logger.notice("Начало загрузки настроек системы")

    try:
        store_base_settings(settings)
        logger.notice("Настройки системы успешно загружены")

    except ValueError as error:
        logger.error("Ошибка при загрузке настроек системы: %s", str(error))


def _seed_enterprise_settings(seed_config: SeedConfiguration) -> None:
    """Загружает корпоративные настройки системы.

    Обрабатывает основные настройки системы и переопределения элементов навигации.
    Объединяет настройки из конфигурации с SVG логотипами из файлов.

    Args:
        seed_config: Конфигурация с настройками для загрузки
    """
    has_enterprise_settings = seed_config.enterprise_settings is not None
    has_nav_overrides = seed_config.nav_item_overrides is not None

    # Если нет настроек для загрузки - выходим
    if not has_enterprise_settings and not has_nav_overrides:
        return

    # Создаем базовые настройки системы
    if has_enterprise_settings:
        enterprise_settings = deepcopy(seed_config.enterprise_settings)
    else:
        enterprise_settings = EnterpriseSettings()

    # Обрабатываем переопределения элементов навигации
    navigation_items = enterprise_settings.custom_nav_items
    if has_nav_overrides:
        navigation_items = []

        for nav_override in seed_config.nav_item_overrides:
            try:
                # Читаем SVG содержимое из файла
                with open(nav_override.svg_path, "r") as svg_file:
                    svg_content = svg_file.read().strip()

                # Создаем элемент навигации с SVG логотипом
                nav_item = NavigationItem(
                    link=nav_override.link,
                    title=nav_override.title,
                    svg_logo=svg_content,
                )
                navigation_items.append(nav_item)

            except Exception as error:
                logger.error(
                    "Ошибка при загрузке SVG для элемента навигации %s: %s",
                    nav_override.title, str(error),
                )

    enterprise_settings.custom_nav_items = navigation_items

    logger.notice("Загрузка системных настроек")
    store_ee_settings(enterprise_settings)
    logger.notice("Системные настройки успешно загружены")


def _seed_logo(db_session: Session, logo_path: str | None) -> None:
    """Загружает логотип системы из указанного пути.

    Args:
        logo_path: Путь к файлу логотипа или None если логотип не нужно загружать
    """
    if logo_path:
        logger.notice("Загрузка логотипа системы")
        upload_logo(db_session=db_session, file=logo_path)


def _seed_analytics_script(seed_config: SeedConfiguration) -> None:
    """Загружает аналитический скрипт системы из файла.

    Args:
        seed_config: Конфигурация с путем к аналитическому скрипту
    """
    analytics_secret_key = os.environ.get("CUSTOM_ANALYTICS_SECRET_KEY")
    has_script_path = seed_config.analytics_script_path is not None
    has_secret_key = analytics_secret_key is not None

    if has_script_path and has_secret_key:
        logger.notice("Загрузка аналитического скрипта системы")

        try:
            # Читаем содержимое скрипта из файла
            with open(seed_config.analytics_script_path, "r") as script_file:
                script_content = script_file.read()

            # Создаем объект для загрузки скрипта
            analytics_script_data = AnalyticsScriptUpload(
                script=script_content,
                secret_key=analytics_secret_key,
            )

            # Сохраняем скрипт в системе
            store_analytics_script(analytics_script_data)
            logger.debug("Аналитический скрипт успешно загружен")

        except FileNotFoundError:
            logger.error(
                "Файл аналитического скрипта не найден: %s",
                seed_config.analytics_script_path,
            )
        except ValueError as error:
            logger.error("Ошибка при загрузке аналитического скрипта: %s", str(error))


def get_seed_config() -> SeedConfiguration | None:
    """Получает конфигурацию для инициализации системы из переменных окружения.

    Returns:
        Конфигурация инициализации или None, если конфигурация не задана
    """
    return _parse_env()


def seed_db() -> None:
    """Выполняет полную инициализацию системы из конфигурации.

    Загружает все компоненты системы: языковые модели, ассистентов, настройки,
    инструменты, логотипы и аналитические скрипты.
    """
    seed_config = _parse_env()

    # Если конфигурация не задана - выходим
    if seed_config is None:
        logger.debug("Файл конфигурации инициализации не передан")
        return

    with get_session_context_manager() as db_session:
        if seed_config.llms is not None:
            _seed_llms(db_session, seed_config.llms)
        if seed_config.personas is not None:
            _seed_personas(db_session, seed_config.personas)
        if seed_config.settings is not None:
            _seed_settings(seed_config.settings)
        if seed_config.custom_tools is not None:
            _seed_custom_tools(db_session, seed_config.custom_tools)

        _seed_logo(db_session, seed_config.seeded_logo_path)
        _seed_enterprise_settings(seed_config)
        _seed_analytics_script(seed_config)

        logger.notice("Проверка наличия стандартной категории ответов по умолчанию")
        create_initial_default_standard_answer_category(db_session)

    logger.notice("Инициализация системы завершена")
