from collections import OrderedDict
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from smartsearch.onyx.server.manage.models import StandardAnswer
from onyx.chat.models import (
    CitationInfo,
    PersonaOverrideConfig,
    QADocsResponse,
    SubQuestionIdentifier,
    ThreadMessage,
)
from onyx.context.search.enums import LLMEvaluationType, SearchType
from onyx.context.search.models import (
    ChunkContext,
    RerankingDetails,
    RetrievalDetails,
    SavedSearchDoc,
)


class StandardAnswerRequest(BaseModel):
    """Модель запроса для поиска стандартных ответов"""

    message: str = Field(
        description="Текст сообщения пользователя для поиска соответствий",
    )
    slack_bot_categories: list[str] = Field(
        description="Список категорий Slack бота, в которых следует искать стандартные ответы",
    )


class StandardAnswerResponse(BaseModel):
    """Модель ответа со стандартными ответами"""

    standard_answers: list[StandardAnswer] = Field(
        default_factory=list,
        description="Список найденных стандартных ответов, соответствующих запросу",
    )


class DocumentSearchRequest(ChunkContext):
    """Запрос на поиск документов в базе знаний"""

    message: str = Field(
        description="Текст поискового запроса для поиска документов"
    )
    search_type: SearchType = Field(
        description="Тип поиска: SEMANTIC (семантический), KEYWORD (по ключевым словам). "
                    "Определяет алгоритм поиска и ранжирования."
    )
    retrieval_options: RetrievalDetails = Field(
        description="Детальные настройки извлечения документов"
    )
    recency_bias_multiplier: float = Field(
        default=1.0,
        description="Множитель смещения в сторону новых документов. "
                    "Значение 1.0 - нейтрально, >1.0 - приоритет новым документам, "
                    "<1.0 - уменьшает влияние новизны на ранжирование."
    )
    evaluation_type: LLMEvaluationType = Field(
        description="Способ оценки релевантности с помощью языковой модели: "
                   "AGENTIC (агентская оценка), BASIC (булева оценка), "
                   "SKIP (пропустить оценку), UNSPECIFIED (настройки по умолчанию)."
    )
    rerank_settings: RerankingDetails | None = Field(
        default=None,
        description="Параметры повторного ранжирования результатов. "
                   "Если None или num_rerank=0 - реранжирование отключено. "
                   "Позволяет настроить модель, провайдера и количество документов для реранжирования."
    )


class BasicCreateChatMessageRequest(ChunkContext):
    """Запрос на создание упрощенного сообщения в чате.

    Перед отправкой сообщения необходимо создать чат-сессию и получить её идентификатор.
    Для простоты использования поддерживается только линейная цепочка сообщений.
    """

    chat_session_id: UUID = Field(
        description="Уникальный идентификатор существующей чат-сессии",
    )
    message: str = Field(
        description="Текст нового сообщения пользователя",
    )
    retrieval_options: RetrievalDetails | None = Field(
        description="Настройки поиска документов. "
                    "По умолчанию - поиск без дополнительных фильтров",
        default=None,
    )
    query_override: str | None = Field(
        description="Позволяет указать точный поисковый запрос. "
                    "При указании отключает автоматическое перефразирование",
        default=None,
    )
    search_doc_ids: list[int] | None = Field(
        description="Конкретные идентификаторы документов для поиска. "
                    "При указании игнорирует настройки retrieval_options",
        default=None,
    )
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = Field(
        description="Формат структурированного ответа (только для OpenAI)",
        default=None,
    )

    use_agentic_search: bool = Field(
        description="Использование агентного поиска вместо базового."
                    "Если True - используется агентский поиск, иначе - базовый.",
        default=False,
    )


class BasicCreateChatMessageWithHistoryRequest(ChunkContext):
    """Запрос на обработку сообщения чата с историей диалога"""

    messages: list[ThreadMessage] = Field(
        description="Список сообщений: последний элемент - новый запрос, остальные - история",
    )
    prompt_id: int | None = Field(
        description="Идентификатор промпта",
        default=None,
    )
    persona_id: int = Field(
        description="Идентификатор ассистента",
    )
    retrieval_options: RetrievalDetails | None = Field(
        description="Настройки поиска документов. "
                    "По умолчанию - поиск без дополнительных фильтров",
        default=None,
    )
    query_override: str | None = Field(
        description="Позволяет указать точный поисковый запрос. "
                    "При указании отключает автоматическое перефразирование",
        default=None,
    )
    skip_rerank: bool | None = Field(
        description="Пропуск переранжирования результатов",
        default=None,
    )
    search_doc_ids: list[int] | None = Field(
        description="Конкретные идентификаторы документов для поиска. "
                    "При указании игнорирует настройки retrieval_options",
        default=None,
    )
    # https://platform.openai.com/docs/guides/structured-outputs/introduction
    structured_response_format: dict | None = Field(
        description="Формат структурированного ответа (только для OpenAI)",
        default=None,
    )
    use_agentic_search: bool = Field(
        description="Использование агентного поиска вместо базового."
                    "Если True - используется агентский поиск, иначе - базовый.",
        default=False,
    )


class AgentSubQuestion(SubQuestionIdentifier):
    """Подвопрос, сгенерированный агентом"""

    sub_question: str = Field(description="Текст подвопроса для дальнейшего исследования")
    document_ids: list[str] = Field(description="ID документов, связанных с этим подвопросом")


class AgentAnswer(SubQuestionIdentifier):
    """Ответ агента на подвопрос или итоговый ответ """

    answer: str
    answer: str = Field(description="Текст ответа, сгенерированного агентом")
    answer_type: Literal["agent_sub_answer", "agent_level_answer"] = Field(
        description="Тип ответа: подответ или итоговый ответ уровня"
    )


class AgentSubQuery(SubQuestionIdentifier):
    """Поисковый запрос, сгенерированный агентом для подвопроса."""

    sub_query: str = Field(description="Текст поискового запроса для подвопроса")
    query_id: int = Field(description="Уникальный идентификатор запроса в рамках подвопроса")

    @staticmethod
    def make_dict_by_level_and_question_index(
        original_dict: dict[tuple[int, int, int], "AgentSubQuery"],
    ) -> dict[int, dict[int, list["AgentSubQuery"]]]:
        """Группирует подзапросы по уровням и номерам вопросов.

        Преобразует словарь с ключами (уровень, вопрос, запрос) в структуру:
        уровень -> номер_вопроса -> список запросов, отсортированных по query_id
        """

        # Группируем запросы по уровням и вопросам
        level_question_dict: dict[int, dict[int, list["AgentSubQuery"]]] = {}
        for k1, obj in original_dict.items():
            level = k1[0]
            question = k1[1]

            if level not in level_question_dict:
                level_question_dict[level] = {}

            if question not in level_question_dict[level]:
                level_question_dict[level][question] = []

            level_question_dict[level][question].append(obj)

        # Сортируем запросы внутри каждого вопроса
        for key1, obj1 in level_question_dict.items():
            for key2, value2 in obj1.items():
                level_question_dict[key1][key2] = sorted(
                    value2, key=lambda o: o.query_id
                )
            # Сортируем вопросы внутри уровня
            level_question_dict[key1] = OrderedDict(
                sorted(level_question_dict[key1].items(), key=lambda x: (x is None, x))
            )

        # Сортируем уровни
        sorted_dict = OrderedDict(
            sorted(level_question_dict.items(), key=lambda x: (x is None, x))
        )
        return sorted_dict


class ChatBasicResponse(BaseModel):
    """Базовый ответ чат-ассистента с минимальным набором данных"""

    answer: str | None = Field(
        description="Текст ответа ассистента",
        default=None,
    )
    answer_citationless: str | None = Field(
        description="Текст ответа без цитат",
        default=None,
    )

    top_documents: list[SavedSearchDoc] | None = Field(
        description="Топ документы из поиска",
        default=None,
    )

    error_msg: str | None = Field(
        description="Сообщение об ошибке",
        default=None,
    )
    message_id: int | None = Field(
        description="Идентификатор сообщения",
        default=None,
    )
    llm_selected_doc_indices: list[int] | None = Field(
        description="Индексы документов, выбранные LLM",
        default=None,
    )
    final_context_doc_indices: list[int] | None = Field(
        description="Индексы документов в финальном контексте",
        default=None,
    )
    cited_documents: dict[int, str] | None = Field(
        description="Соответствие номеров цитат идентификаторам документов",
        default=None,
    )

    llm_chunks_indices: list[int] | None = Field(
        description="Индексы документов, отобранные LLM для ответа "
                    "(устаревшее поле, дублирует llm_selected_doc_indices)",
        default=None,
    )

    # Поля для агента
    agent_sub_questions: dict[int, list[AgentSubQuestion]] | None = Field(
        description="Вопросы агентного поиска по уровням",
        default=None,
    )
    agent_answers: dict[int, list[AgentAnswer]] | None = Field(
        description="Ответы агентного поиска по уровням",
        default=None,
    )
    agent_sub_queries: dict[int, dict[int, list[AgentSubQuery]]] | None = Field(
        description="Подзапросы агентного поиска",
        default=None,
    )
    agent_refined_answer_improvement: bool | None = Field(
        description="Флаг улучшения ответа агентом",
        default=None,
    )


class OneShotQARequest(ChunkContext):
    """Модель запроса для единичного вопроса-ответа
    без управления историей чата.
    """

    persona_override_config: PersonaOverrideConfig | None = Field(
        default=None,
        description="Кастомная конфигурация ассистента для переопределения стандартных настроек. "
                    "Альтернатива использованию persona_id для гибкой настройки поведения ИИ."
    )
    persona_id: int | None = Field(
        default=None,
        description="ID ассистента. "
                    "Должен быть указан один из параметров: persona_id или persona_override_config."
    )

    messages: list[ThreadMessage] = Field(description="Список сообщений")
    prompt_id: int | None = Field(default=None, description="ID промпта")
    retrieval_options: RetrievalDetails = Field(
        default_factory=RetrievalDetails,
        description="Настройки поиска и извлечения документов из базы знаний."
    )
    rerank_settings: RerankingDetails | None = Field(
        default=None,
        description="Настройки повторного ранжирования результатов поиска для улучшения релевантности."
    )
    return_contexts: bool = Field(
        default=False,
        description="Флаг возврата контекстных документов в ответе. "
                    "Если True, в ответе будут включены документы, использованные для генерации."
    )

    query_override: str | None = Field(
        default=None,
        description="Прямое указание поискового запроса вместо использования текста сообщения. "
                    "Позволяет использовать разные запросы для поиска и для LLM. "
                    "При указании отключает перефразирование на основе треда сообщений."
    )

    skip_gen_ai_answer_generation: bool = Field(
        default=False,
        description="Пропустить генерацию ответа ИИ. "
                    "Если True, выполняется только поиск документов без генерации текстового ответа."
    )

    use_agentic_search: bool = Field(
        default=False,
        description="Использовать агентский поиск вместо базового. "
                    "Агентский поиск обеспечивает более интеллектуальное извлечение информации "
                    "через многоэтапный процесс анализа."
    )

    @model_validator(mode="after")
    def check_persona_fields(self) -> "OneShotQARequest":
        """Проверяет корректность настроек персоналии и связанных полей.

        Валидирует что:
            - Указана ровно одна конфигурация ассистента (стандартная или кастомная)
            - При использовании кастомной конфигурации не указаны конфликтующие поля
        """
        # Проверяем, что указана хотя бы одна конфигурация ассистента
        if self.persona_override_config is None and self.persona_id is None:
            raise ValueError(
                "Необходимо указать одну из конфигураций ассистента: "
                "persona_id для стандартного или persona_override_config для кастомного"
            )

        # Проверяем что при кастомной конфигурации нет конфликтующих полей
        elif self.persona_override_config is not None:
            if self.persona_id is not None:
                raise ValueError(
                    "При использовании кастомной конфигурации ассистента (persona_override_config) "
                    "нельзя указывать стандартный persona_id"
                )
            if self.prompt_id is not None:
                raise ValueError(
                    "При использовании кастомной конфигурации ассистента (persona_override_config) "
                    "нельзя указывать prompt_id"
                )

        return self


class OneShotQAResponse(BaseModel):
    """Модель ответа для единичного вопроса-ответа"""

    answer: str | None = Field(
        default=None,
        description="Текст ответа на запрос",
    )
    rephrase: str | None = Field(
        default=None,
        description="Перефразированная версия исходного запроса после обработки системой",
    )
    citations: list[CitationInfo] | None = Field(
        default=None,
        description="Список цитат и ссылок на источники, использованные при формировании ответа",
    )
    docs: QADocsResponse | None = Field(
        default=None,
        description="Документы, найденные в процессе поиска и использованные для ответа.",
    )
    llm_selected_doc_indices: list[int] | None = Field(
        default=None,
        description="Индексы документов, отобранные для финального контекста из исходных результатов поиска.",
    )
    error_msg: str | None = Field(
        default=None,
        description="Сообщение об ошибке при сбое в процессе обработки запроса.",
    )
    chat_message_id: int | None = Field(
        default=None,
        description="Идентификатор созданного сообщения в системе для отслеживания истории.",
    )
