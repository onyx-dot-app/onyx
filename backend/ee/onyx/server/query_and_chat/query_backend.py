import json
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ee.onyx.chat.process_message import gather_stream_for_answer_api
from ee.onyx.onyxbot.slack.handlers.handle_standard_answers import (
    oneoff_standard_answers,
)
from ee.onyx.server.query_and_chat.models import (
    DocumentSearchRequest,
    OneShotQARequest,
    OneShotQAResponse,
    StandardAnswerRequest,
    StandardAnswerResponse,
)
from onyx.auth.users import current_user
from onyx.chat.chat_utils import (
    combine_message_thread,
    prepare_chat_message_request,
)
from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.process_message import (
    ChatPacketStream,
    stream_chat_message_objects,
)
from onyx.configs.onyxbot_configs import MAX_THREAD_CONTEXT_PERCENTAGE
from onyx.context.search.models import (
    SavedSearchDocWithContent,
    InferenceSection,
    SearchRequest,
)
from onyx.context.search.pipeline import SearchPipeline
from onyx.context.search.utils import (
    dedupe_documents,
    drop_llm_indices,
    relevant_sections_to_indices,
)
from onyx.db.chat import get_prompt_by_id
from onyx.db.engine import get_session
from onyx.db.models import Persona, User
from onyx.db.persona import get_persona_by_id
from onyx.llm.factory import (
    get_default_llms,
    get_llms_for_persona,
    get_main_llm_from_tuple,
)
from onyx.llm.utils import get_max_input_tokens
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger

logger = setup_logger()

basic_router = APIRouter(tags=["Поиск документов и ответы с цитатами"])


class DocumentSearchResponse(BaseModel):
    """Ответ с результатами поиска документов"""

    top_documents: list[SavedSearchDocWithContent] = Field(
        description="Список найденных документов, отсортированный по релевантности"
    )
    llm_indices: list[int] = Field(
        description="Индексы документов из top_documents, которые были признаны релевантными "
                    "языковой моделью"
    )


def _convert_sections_to_search_docs(
    sections: list[InferenceSection]
) -> list[SavedSearchDocWithContent]:
    """Преобразует внутренние секции в формат документов для ответа"""

    return [
            SavedSearchDocWithContent(
                document_id=section.center_chunk.document_id,
                chunk_ind=section.center_chunk.chunk_id,
                content=section.center_chunk.content,
                semantic_identifier=section.center_chunk.semantic_identifier or "Unknown",
                link=(
                    section.center_chunk.source_links.get(0)
                    if section.center_chunk.source_links
                    else None
                ),
                blurb=section.center_chunk.blurb,
                source_type=section.center_chunk.source_type,
                boost=section.center_chunk.boost,
                hidden=section.center_chunk.hidden,
                metadata=section.center_chunk.metadata,
                score=section.center_chunk.score or 0.0,
                match_highlights=section.center_chunk.match_highlights,
                updated_at=section.center_chunk.updated_at,
                primary_owners=section.center_chunk.primary_owners,
                secondary_owners=section.center_chunk.secondary_owners,
                is_internet=False,
                db_doc_id=0,
            )
            for section in sections
        ]


@basic_router.post(
    "/query/document-search",
    summary="Поиск документов по запросу",
    response_model=DocumentSearchResponse,
)
def handle_search_request(
    search_request: DocumentSearchRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DocumentSearchResponse:
    """Выполняет поиск документов по текстовому запросу с фильтрацией и ранжированием.

    Эндпоинт предоставляет полнофункциональный поиск по базе знаний с поддержкой:
        - Семантического и гибридного поиска
        - Фильтрации по метаданным и правам доступа
        - Ранжирования и реранжирования результатов
        - Дедупликации документов
        - Определения релевантности с помощью LLM

    Особенности:
        - Не создает сообщений в истории чата
        - Не сохраняет результаты в базу данных
        - Возвращает полное содержимое найденных документов

    Args:
        search_request: Параметры поискового запроса

    Returns:
        Результаты поиска с документами и индексами релевантности

    Raises:
        HTTPException: При ошибках выполнения поискового запроса
    """
    query_text = search_request.message
    logger.notice(f"Получен запрос на поиск документов: {query_text}")

    try:
        # Инициализируем языковые модели для обработки запроса
        main_llm, fast_llm = get_default_llms()

        # Создаем и настраиваем поисковый пайплайн
        search_pipeline = SearchPipeline(
            search_request=SearchRequest(
                query=query_text,
                search_type=search_request.search_type,
                human_selected_filters=search_request.retrieval_options.filters,
                enable_auto_detect_filters=search_request.retrieval_options.enable_auto_detect_filters,
                persona=None,  # Для простоты используем настройки по умолчанию
                offset=search_request.retrieval_options.offset,
                limit=search_request.retrieval_options.limit,
                rerank_settings=search_request.rerank_settings,
                evaluation_type=search_request.evaluation_type,
                chunks_above=search_request.chunks_above,
                chunks_below=search_request.chunks_below,
                full_doc=search_request.full_doc,
            ),
            user=user,
            llm=main_llm,
            fast_llm=fast_llm,
            skip_query_analysis=False,
            db_session=db_session,
            bypass_acl=False,
        )

        # Получаем результаты поиска
        top_sections = search_pipeline.reranked_sections
        relevance_sections = search_pipeline.section_relevance

        # Преобразуем секции в формат для ответа
        top_docs_result = _convert_sections_to_search_docs(sections=top_sections)

        # Дедупликация выполняется на последнем этапе, чтобы избежать потери качества
        # из-за преждевременного удаления контента
        deduped_docs = top_docs_result
        dropped_inds = None

        if search_request.retrieval_options.dedupe_docs:
            deduped_docs, dropped_inds = dedupe_documents(items=top_docs_result)

        llm_indices = relevant_sections_to_indices(
            relevance_sections=relevance_sections, items=deduped_docs
        )

        if dropped_inds:
            llm_indices = drop_llm_indices(
                llm_indices=llm_indices,
                search_docs=deduped_docs,
                dropped_indices=dropped_inds,
            )

        document_search_response = DocumentSearchResponse(
            top_documents=deduped_docs, llm_indices=llm_indices
        )

        return document_search_response

    except Exception as e:
        logger.error(f"Ошибка при выполнении поиска документов: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Произошла ошибка при выполнении поиска")


def _get_persona_info(
    query_request: OneShotQARequest,
    user: User | None,
    db_session: Session,
) -> Persona | PersonaOverrideConfig | None:
    """Получает конфигурацию ассистента на основе запроса.

    Args:
        query_request: Запрос с настройками ассистента
        user: Пользователь для проверки прав доступа
        db_session: Сессия базы данных

    Returns:
        Конфигурация ассистента (стандартная или кастомная)

    Raises:
        ValueError: Если ассистент не найден или нет прав доступа
    """
    if query_request.persona_override_config is not None:
        return query_request.persona_override_config

    elif query_request.persona_id is not None:
        return get_persona_by_id(
            persona_id=query_request.persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )


def get_answer_stream(
    query_request: OneShotQARequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatPacketStream:
    """Создает поток обработки запроса для формирования ответа.

    Подготавливает конфигурацию ассистента, промпты и параметры поиска,
    затем запускает потоковую обработку сообщения.

    Args:
        query_request: Запрос на обработку с настройками ассистента и поиска

    Returns:
        Поток пакетов с результатами обработки

    Raises:
        KeyError: Если не указана конфигурация ассистента
        Exception: При ошибках загрузки конфигурации или обработки запроса
    """
    query_text = query_request.messages[0].message
    logger.notice(f"Получен запрос для обработки: {query_text}")

    if (
        query_request.persona_override_config is None
        and query_request.persona_id is None
    ):
        raise KeyError("Необходимо указать persona_id или persona_override_config")

    prompt_config = None
    if query_request.prompt_id is not None:
        prompt_config = get_prompt_by_id(
            prompt_id=query_request.prompt_id,
            user=user,
            db_session=db_session,
        )

    # Определяем конфигурацию ассистента
    persona_info: Persona | PersonaOverrideConfig | None = _get_persona_info(
        query_request=query_request, user=user, db_session=db_session
    )

    # Получаем пару моделей (основная и быстрая) для ассистента
    llm_models_for_persona = get_llms_for_persona(persona_info)
    # Извлекаем основную модель из пары
    main_llm = get_main_llm_from_tuple(llms=llm_models_for_persona)

    # Подготавливаем токенизатор и рассчитываем контекст
    llm_tokenizer = get_tokenizer(
        model_name=main_llm.config.model_name,
        provider_type=main_llm.config.model_provider,
    )

    # Рассчитываем максимальное количество токенов для истории
    max_input_tokens = get_max_input_tokens(
        model_name=main_llm.config.model_name,
        model_provider=main_llm.config.model_provider,
    )
    max_history_tokens = int(max_input_tokens * MAX_THREAD_CONTEXT_PERCENTAGE)

    combined_message = combine_message_thread(
        messages=query_request.messages,
        max_tokens=max_history_tokens,
        llm_tokenizer=llm_tokenizer,
    )

    # Создаем запрос на обработку сообщения
    request = prepare_chat_message_request(
        message_text=combined_message,
        user=user,
        persona_id=query_request.persona_id,
        persona_override_config=query_request.persona_override_config,
        prompt=prompt_config,
        message_ts_to_respond_to=None,
        retrieval_details=query_request.retrieval_options,
        rerank_settings=query_request.rerank_settings,
        db_session=db_session,
        use_agentic_search=query_request.use_agentic_search,
        skip_gen_ai_answer_generation=query_request.skip_gen_ai_answer_generation,
    )

    # Запускаем потоковую обработку
    packets = stream_chat_message_objects(
        new_msg_req=request,
        user=user,
        db_session=db_session,
        include_contexts=query_request.return_contexts,
    )

    return packets


@basic_router.post(
    "/query/answer-with-citation",
    summary="Получить ответ с цитированием ответа (не потоковое)",
    response_model=OneShotQAResponse,
)
def get_answer_with_citation(
    request: OneShotQARequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> OneShotQAResponse:
    """Синхронно возвращает ответ ИИ на запрос с цитированием использованных источников.

    Обрабатывает запрос через потоковую генерацию и собирает все данные в единый ответ.
    Включает текст ответа, перефразированный запрос, цитаты и использованные документы.

    Args:
        request: Запрос на генерацию ответа с настройками ассистента и поиска

    Returns:
        Полный ответ ИИ с цитатами и метаданными

    Raises:
        HTTPException: В случае ошибок обработки запроса или генерации ответа
    """
    try:
        # Получаем поток пакетов с ответом
        packet_stream = get_answer_stream(
            query_request=request,
            user=user,
            db_session=db_session
        )

        # Собираем поток в структурированный ответ
        answer_response = gather_stream_for_answer_api(packet_stream)

        # Проверяем наличие ошибки в ответе
        if answer_response.error_msg:
            raise RuntimeError(f"Ошибка генерации ответа: {answer_response.error_msg}")

        return answer_response

    except Exception as e:
        logger.error(
            f"Ошибка в get_answer_with_citation: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Произошла внутренняя ошибка сервера",
        )


@basic_router.post(
    "/query/stream-answer-with-citation",
    summary="Потоковое получение ответа с цитированием источников",
)
def stream_answer_with_citation(
    request: OneShotQARequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    """Потоково возвращает ответ ИИ на запрос с цитированием использованных источников.

    Эндпоинт предоставляет ответ в реальном времени по мере генерации моделью ИИ.
    Каждый пакет данных сериализуется в JSON-line формат и отправляется клиенту.

    Args:
        request: Запрос на генерацию ответа с настройками персоналии и поиска

    Returns:
        StreamingResponse: Потоковый ответ в формате application/json

    Raises:
        HTTPException: В случае ошибок обработки запроса
    """
    def stream_generator() -> Generator[str, None, None]:
        try:
            # Получаем поток заранее для централизованной обработки ошибок
            packet_stream = get_answer_stream(
                query_request=request,
                user=user,
                db_session=db_session
            )

            for packet in packet_stream:
                serialized_packet = get_json_line(packet.model_dump())
                yield serialized_packet

        except Exception as e:
            logger.exception("Ошибка в потоковой передаче ответа")
            yield json.dumps({"error": str(e)})

    streaming_response = StreamingResponse(stream_generator(), media_type="application/json")

    return streaming_response


@basic_router.get(
    "/query/standard-answer",
    summary="Получить стандартные ответы для сообщения",
    response_model=StandardAnswerResponse,
)
def get_standard_answer(
    request: StandardAnswerRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> StandardAnswerResponse:
    """Возвращает стандартные ответы, соответствующие пользовательскому сообщению.

    Ищет предварительно настроенные стандартные ответы в указанных категориях Slack бота,
    которые соответствуют тексту сообщения пользователя.

    Args:
        request: Запрос со сообщением и категориями для поиска

    Returns:
        Стандартные ответы, соответствующие запросу

    Raises:
        HTTPException: В случае внутренней ошибки сервера
    """
    try:
        standard_answers = oneoff_standard_answers(
            message=request.message,
            slack_bot_categories=request.slack_bot_categories,
            db_session=db_session,
        )
        return StandardAnswerResponse(
            standard_answers=standard_answers
        )
    except Exception as e:
        logger.error(
            f"Ошибка в функции get_standard_answer: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Произошла внутренняя ошибка сервера",
        )
