import re
from typing import cast, Union

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from smartsearch.onyx.server.query_and_chat.models import (
    AgentAnswer,
    AgentSubQuery,
    AgentSubQuestion,
    BasicCreateChatMessageRequest,
    BasicCreateChatMessageWithHistoryRequest,
    ChatBasicResponse,
)
from onyx.auth.users import api_key_dep
from onyx.chat.chat_utils import combine_message_thread
from onyx.chat.chat_utils import create_chat_chain
from onyx.chat.models import (
    AgentAnswerPiece,
    AllCitations,
    ExtendedToolResponse,
    FinalUsedContextDocsResponse,
    LlmDoc,
    LLMRelevanceFilterResponse,
    OnyxAnswerPiece,
    QADocsResponse,
    RefinedAnswerImprovement,
    StreamingError,
    SubQueryPiece,
    SubQuestionIdentifier,
    SubQuestionPiece,
)
from onyx.chat.process_message import (
    ChatPacketStream,
    stream_chat_message_objects,
)
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.constants import MessageType
from onyx.context.search.models import (
    OptionalSearchSetting,
    RetrievalDetails,
    SavedSearchDoc,
)
from onyx.db.chat import (
    create_chat_session,
    create_new_chat_message,
    get_or_create_root_message,
)
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.llm.factory import get_llms_for_persona
from onyx.llm.utils import get_max_input_tokens
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.secondary_llm_flows.query_expansion import thread_based_query_rephrase
from onyx.server.query_and_chat.models import (
    ChatMessageDetail,
    CreateChatMessageRequest,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(tags=["Обработка сообщений без стриминга (send-message)"])


def _get_final_context_doc_indices(
    final_context_docs: list[LlmDoc] | None,
    top_docs: list[SavedSearchDoc] | None,
) -> list[int] | None:
    """Возвращает список индексов документов простого поиска, 
    которые были фактически переданы в LLM.

    Args:
        final_context_docs: Список документов, фактически использованных в контексте LLM
        top_docs: Список топовых документов из поиска

    Returns:
        Список индексов документов из top_docs, которые были использованы в финальном контексте,
        или None если входные данные некорректны
    """
    if final_context_docs is None or top_docs is None:
        return None

    # Собираем ID документов из финального контекста
    final_context_doc_ids = set()
    for document in final_context_docs:
        final_context_doc_ids.add(document.document_id)

    # Находим индексы использованных документов в результатах поиска
    used_doc_indices = []
    for search_document_index, search_document in enumerate(top_docs):
        if search_document.document_id in final_context_doc_ids:
            used_doc_indices.append(search_document_index)

    return used_doc_indices


def _process_packets_loop(
    packets: ChatPacketStream,
    response: ChatBasicResponse,
    agent_sub_questions: dict[tuple[int, int], AgentSubQuestion],
    agent_answers: dict[tuple[int, int], AgentAnswer],
    agent_sub_queries: dict[tuple[int, int, int], AgentSubQuery],
    final_context_docs: list[LlmDoc],
) -> str:
    """Обрабатывает каждый пакет в потоке и заполняет соответствующие структуры данных.

    Args:
        packets: Поток пакетов для обработки
        response: Объект ответа для заполнения
        agent_sub_questions: Словарь подвопросов агента
        agent_answers: Словарь ответов агента
        agent_sub_queries: Словарь подзапросов агента
        final_context_docs: Список финальных документов

    Returns:
        Собранный текстовый ответ
    """
    answer = ""

    # Обработка каждого пакета в потоке
    for packet in packets:
        if isinstance(packet, OnyxAnswerPiece) and packet.answer_piece:
            answer += packet.answer_piece
        elif isinstance(packet, QADocsResponse):
            response.top_documents = packet.top_documents

            # Это не будет работать, если agent_sub_questions еще не заполнен
            if packet.level is not None and packet.level_question_num is not None:
                id = (packet.level, packet.level_question_num)
                if id in agent_sub_questions:
                    agent_sub_questions[id].document_ids = [
                        saved_search_doc.document_id
                        for saved_search_doc in packet.top_documents
                    ]

        elif isinstance(packet, StreamingError):
            response.error_msg = packet.error
        elif isinstance(packet, ChatMessageDetail):
            response.message_id = packet.message_id
        elif isinstance(packet, LLMRelevanceFilterResponse):
            response.llm_selected_doc_indices = packet.llm_selected_doc_indices

            # TODO: deprecate `llm_chunks_indices`
            response.llm_chunks_indices = packet.llm_selected_doc_indices
        elif isinstance(packet, FinalUsedContextDocsResponse):
            final_context_docs.extend(packet.final_context_docs)
        elif isinstance(packet, AllCitations):
            response.cited_documents = {
                citation.citation_num: citation.document_id
                for citation in packet.citations
            }
        # Пакеты агентного поиска
        elif isinstance(packet, SubQuestionPiece):
            if packet.level is not None and packet.level_question_num is not None:
                id = (packet.level, packet.level_question_num)
                if agent_sub_questions.get(id) is None:
                    agent_sub_questions[id] = AgentSubQuestion(
                        level=packet.level,
                        level_question_num=packet.level_question_num,
                        sub_question=packet.sub_question,
                        document_ids=[],
                    )
                else:
                    agent_sub_questions[id].sub_question += packet.sub_question

        elif isinstance(packet, AgentAnswerPiece):
            if packet.level is not None and packet.level_question_num is not None:
                id = (packet.level, packet.level_question_num)
                if agent_answers.get(id) is None:
                    agent_answers[id] = AgentAnswer(
                        level=packet.level,
                        level_question_num=packet.level_question_num,
                        answer=packet.answer_piece,
                        answer_type=packet.answer_type,
                    )
                else:
                    agent_answers[id].answer += packet.answer_piece
        elif isinstance(packet, SubQueryPiece):
            if packet.level is not None and packet.level_question_num is not None:
                sub_query_id = (
                    packet.level,
                    packet.level_question_num,
                    packet.query_id,
                )
                if agent_sub_queries.get(sub_query_id) is None:
                    agent_sub_queries[sub_query_id] = AgentSubQuery(
                        level=packet.level,
                        level_question_num=packet.level_question_num,
                        sub_query=packet.sub_query,
                        query_id=packet.query_id,
                    )
                else:
                    agent_sub_queries[sub_query_id].sub_query += packet.sub_query
        elif isinstance(packet, ExtendedToolResponse):
            # Мы не должны получать это. Это перехватывается и преобразуется в QADocsResponse
            logger.warning(
                "_convert_packet_stream_to_response: Неожиданный тип чат-пакета ExtendedToolResponse!"
            )
        elif isinstance(packet, RefinedAnswerImprovement):
            response.agent_refined_answer_improvement = (
                packet.refined_answer_improvement
            )
        else:
            logger.warning(
                "_convert_packet_stream_to_response - Неизвестный чат-пакет: type=%s",
                type(packet),
            )

    return answer


def _organize_agent_metadata(
    response: ChatBasicResponse,
    agent_sub_questions: dict[tuple[int, int], AgentSubQuestion],
    agent_answers: dict[tuple[int, int], AgentAnswer],
    agent_sub_queries: dict[tuple[int, int, int], AgentSubQuery],
) -> None:
    """Организует и сортирует метаданные агентного поиска для вывода.

    Args:
        response: Объект ответа для заполнения метаданными агента
        agent_sub_questions: Словарь подвопросов агента
        agent_answers: Словарь ответов агента
        agent_sub_queries: Словарь подзапросов агента
    """

    # Организация / сортировка метаданных агентного поиска для вывода
    if len(agent_sub_questions) > 0:
        response.agent_sub_questions = cast(
            dict[int, list[AgentSubQuestion]],
            SubQuestionIdentifier.make_dict_by_level(agent_sub_questions),
        )

    if len(agent_answers) > 0:
        # Возвращает agent_level_answer с первого уровня или с последнего в зависимости
        # от agent_refined_answer_improvement
        response.agent_answers = cast(
            dict[int, list[AgentAnswer]],
            SubQuestionIdentifier.make_dict_by_level(agent_answers),
        )
        if response.agent_answers:
            selected_answer_level = (
                0
                if not response.agent_refined_answer_improvement
                else len(response.agent_answers) - 1
            )
            level_answers = response.agent_answers[selected_answer_level]
            for level_answer in level_answers:
                if level_answer.answer_type != "agent_level_answer":
                    continue

                answer = level_answer.answer
                break

    if len(agent_sub_queries) > 0:
        # Подзапросы часто отправляются с завершающими пробелами... очищаем здесь
        # Возможно исправить в источнике?
        for v in agent_sub_queries.values():
            v.sub_query = v.sub_query.strip()

        response.agent_sub_queries = (
            AgentSubQuery.make_dict_by_level_and_question_index(agent_sub_queries)
        )


def _convert_packet_stream_to_response(
    packets: ChatPacketStream,
) -> ChatBasicResponse:
    """Конвертирует потоковые пакеты чата в структурированный ответ.

    Обрабатывает различные типы пакетов из потокового ответа и собирает их
    в единый объект ChatBasicResponse. Поддерживает базовые ответы, агентный поиск,
    документы, ошибки и цитаты.

    Args:
        packets: Поток пакетов от системы обработки сообщений

    Returns:
        Структурированный ответ со всеми собранными данными
    """
    response = ChatBasicResponse()
    final_context_docs: list[LlmDoc] = []

    # Словари для агрегации данных агентного поиска
    agent_sub_questions: dict[tuple[int, int], AgentSubQuestion] = {}
    agent_answers: dict[tuple[int, int], AgentAnswer] = {}
    agent_sub_queries: dict[tuple[int, int, int], AgentSubQuery] = {}

    # Обработка пакетов в отдельной функции
    answer = _process_packets_loop(
        packets=packets,
        response=response,
        agent_sub_questions=agent_sub_questions,
        agent_answers=agent_answers,
        agent_sub_queries=agent_sub_queries,
        final_context_docs=final_context_docs,
    )

    response.final_context_doc_indices = _get_final_context_doc_indices(
        final_context_docs=final_context_docs,
        top_docs=response.top_documents,
    )

    # Организация метаданных агентного поиска
    _organize_agent_metadata(
        response=response,
        agent_sub_questions=agent_sub_questions,
        agent_answers=agent_answers,
        agent_sub_queries=agent_sub_queries,
    )

    response.answer = answer
    if answer:
        pattern = r"\s*\[\[\d+\]\]\(http[s]?://[^\s]+\)"
        response.answer_citationless = re.sub(pattern, "", answer)

    return response


def _build_search_configuration(
    request: Union[BasicCreateChatMessageRequest, BasicCreateChatMessageWithHistoryRequest],
) -> RetrievalDetails | None:
    """Формирует конфигурацию поиска на основе запроса"""

    if request.retrieval_options is None and request.search_doc_ids is None:
        return RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=False,
        )
    else:
        return request.retrieval_options


@router.post(
    "/chat/send-message-simple-api",
    summary="Обработки сообщений без поддержки истории чата",
    response_model=ChatBasicResponse,
)
def handle_simplified_chat_message(
    chat_message_req: BasicCreateChatMessageRequest,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> ChatBasicResponse:
    """Не стримингвоый эндпоинт для обработки сообщений без поддержки истории чата.

       Не-стриминговый эндпоинт, возвращающий минимальный набор информации.
       Обрабатывает одиночные сообщения без учета контекста предыдущей переписки.

       Отличия от версии с поддержкеой истории чата:
           - Работает с существующей чат-сессией
           - Не выполняет перефразирование на основе истории
           - Поддерживает только линейную цепочку сообщений

       Args:
           chat_message_req: Запрос с данными сообщения
           user: Авторизованный пользователь
           db_session: Сессия базы данных

       Returns:
           Упрощенный ответ ассистента
       """
    logger.notice(
        "Получено новое сообщение (без истории чата): %s",
        chat_message_req.message,
    )

    # Проверка наличия текста сообщения
    if not chat_message_req.message:
        raise HTTPException(
            status_code=400,
            detail="Пустое сообщение недопустимо",
        )

    # Получение родительского сообщения для продолжения цепочки
    try:
        parent_message, _ = create_chat_chain(
            chat_session_id=chat_message_req.chat_session_id,
            db_session=db_session
        )
    except Exception:
        # Создание корневого сообщения, если цепочка не найдена
        parent_message = get_or_create_root_message(
            chat_session_id=chat_message_req.chat_session_id,
            db_session=db_session
        )

    # Конфигурация параметров поиска
    retrieval_options = _build_search_configuration(request=chat_message_req)

    # Формирование полного запроса для обработки
    full_chat_msg_info = CreateChatMessageRequest(
        chat_session_id=chat_message_req.chat_session_id,
        parent_message_id=parent_message.id,
        message=chat_message_req.message,
        file_descriptors=[],
        prompt_id=None,
        search_doc_ids=chat_message_req.search_doc_ids,
        retrieval_options=retrieval_options,
        # Упрощенный API не поддерживает переранжирование
        rerank_settings=None,
        query_override=chat_message_req.query_override,
        # В настоящее время применяется только к поиску, не к чату
        chunks_above=0,
        chunks_below=0,
        full_doc=chat_message_req.full_doc,
        structured_response_format=chat_message_req.structured_response_format,
        use_agentic_search=chat_message_req.use_agentic_search,
    )

    # Обработка сообщения и получение потоковых пакетов
    response_packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
        enforce_chat_session_id_for_search_docs=False,
    )

    # Конвертация потоковых пакетов в финальный ответ
    converted_packets = _convert_packet_stream_to_response(response_packets)

    return converted_packets


@router.post(
    "/chat/send-message-simple-with-history",
    summary="Обработка сообщений с поддержкой истории чата",
    response_model=ChatBasicResponse,
)
def handle_send_message_simple_with_history(
    req: BasicCreateChatMessageWithHistoryRequest,
    user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> ChatBasicResponse:
    """Не стриминговый эндпоинт для обработки сообщений с поддержкой истории чата.

    Не стриминговый эндпоинт, возвращающий минимальный набор
    информации без потоковой передачи. Принимает историю чата,
    поддерживаемую вызывающей стороной, и выполняет перефразирование
    запроса аналогично механизму answer-with-quote.

    Эндпоинт принимает историю переписки и новое сообщение пользователя,
    выполняет контекстуальное перефразирование запроса на основе истории
    и возвращает ответ ассистента. Поддерживает как поиск по документам,
    так и агентный поиск.

    Особенности:
        - Не-стриминговая обработка (единый ответ)
        - Минимальный набор возвращаемых данных
        - Перефразирование запроса с учетом контекста истории
        - Поддержка истории чата от вызывающей стороны
        - Автоматическое перефразирование запроса с учетом контекста истории
        - Поддержка различных режимов поиска (базовый, агентный)
        - Валидация структуры истории сообщений
        - Создание временной чат-сессии для обработки

    Args:
        req: Запрос с историей сообщений и параметрами чата
        user: Аутентифицированный пользователь (через API ключ)
        db_session: Сессия базы данных

    Returns:
        Упрощенный ответ ассистента с минимальным набором данных

    Raises:
        HTTPException:
            - 400: При пустой истории или некорректной структуре сообщений
            - 500: При внутренних ошибках обработки
    """

    # Проверка что история сообщений не пустая
    if len(req.messages) == 0:
        raise HTTPException(
            status_code=400,
            detail="Список сообщений не может быть пустым",
        )

    # Проверка корректности структуры истории чата
    # Должна начинаться с сообщения пользователя и чередоваться пользователь/ассистент
    expected_message_role = MessageType.USER
    for msg in req.messages:
        if not msg.message:
            raise HTTPException(
                status_code=400,
                detail="Одно или несколько сообщений чата пустые",
            )

        if msg.role != expected_message_role:
            raise HTTPException(
                status_code=400,
                detail="Роли сообщений должны начинаться и заканчиваться "
                       "MessageType.USER и чередоваться между ними.",
            )

        if expected_message_role == MessageType.USER:
            expected_message_role = MessageType.ASSISTANT
        else:
            expected_message_role = MessageType.USER

    # Извлечение текущего запроса и истории сообщений
    # req.messages содержит: [история..., текущий_запрос]
    # Последний элемент (-1) - это текущий запрос пользователя
    # Все элементы кроме последнего ([:-1]) - это история переписки
    last_message = req.messages[-1]
    current_user_query = last_message.message
    msg_history = req.messages[:-1]

    logger.notice(
        "Получено новое сообщение (с историей чата): %s",
        current_user_query,
    )

    # Создание чат-сессии
    if user is not None:
        user_id = user.id
    else:
        user_id = None
    chat_session = create_chat_session(
        db_session=db_session,
        description="handle_send_message_simple_with_history",
        user_id=user_id,
        persona_id=req.persona_id,
    )

    # Получение LLM модели для ассистента
    llm, _ = get_llms_for_persona(persona=chat_session.persona)

    # Получение токенизатора для подсчета токенов
    llm_tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )

    # Расчет максимального количества токенов для истории
    input_tokens = get_max_input_tokens(
        model_name=llm.config.model_name,
        model_provider=llm.config.model_provider,
    )
    max_history_tokens = int(input_tokens * CHAT_TARGET_CHUNK_PERCENTAGE)

    # Каждая чат-сессия начинается с пустого корневого сообщения
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id,
        db_session=db_session,
    )

    # Создание цепочки сообщений в базе данных
    chat_message = root_message
    for msg in msg_history:
        chat_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=chat_message,
            prompt_id=req.prompt_id,
            message=msg.message,
            token_count=len(llm_tokenizer.encode(msg.message)),
            message_type=msg.role,
            db_session=db_session,
            commit=False,
        )
    db_session.commit()

    # Комбинирование истории в строку с учетом лимита токенов
    history_str = combine_message_thread(
        messages=msg_history,
        max_tokens=max_history_tokens,
        llm_tokenizer=llm_tokenizer,
    )

    # Перефразирование запроса с учетом истории или использование переопределения
    rephrased_query = req.query_override or thread_based_query_rephrase(
        user_query=current_user_query,
        history_str=history_str,
    )

    # Конфигурация параметров поиска
    retrieval_options = _build_search_configuration(request=req)

    # Формирование полного запроса для обработки
    full_chat_msg_info = CreateChatMessageRequest(
        chat_session_id=chat_session.id,
        parent_message_id=chat_message.id,
        message=current_user_query,
        file_descriptors=[],
        prompt_id=req.prompt_id,
        search_doc_ids=req.search_doc_ids,
        retrieval_options=retrieval_options,
        # Simple API не поддерживает реранкинг, скрываем сложность от пользователя
        rerank_settings=None,
        query_override=rephrased_query,
        chunks_above=0,
        chunks_below=0,
        full_doc=req.full_doc,
        structured_response_format=req.structured_response_format,
        use_agentic_search=req.use_agentic_search,
    )

    # Обработка сообщения и получение потоковых пакетов
    response_packets = stream_chat_message_objects(
        new_msg_req=full_chat_msg_info,
        user=user,
        db_session=db_session,
        enforce_chat_session_id_for_search_docs=False,
    )

    # Конвертация потоковых пакетов в финальный ответ
    converted_packets = _convert_packet_stream_to_response(response_packets)

    return converted_packets
