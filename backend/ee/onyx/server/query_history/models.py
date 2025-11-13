from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from onyx.auth.users import get_display_email
from onyx.configs.constants import MessageType
from onyx.configs.constants import QAFeedbackType
from onyx.configs.constants import SessionType
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession


class AbridgedSearchDoc(BaseModel):
    """Упрощенное представление документа для поиска в 'SearchDoc'"""

    document_id: str = Field(description="Уникальный идентификатор документа")
    semantic_identifier: str = Field(description="Семантический идентификатор документа")
    link: str | None = Field(description="Ссылка на оригинальный документ")


class MessageSnapshot(BaseModel):
    id: int = Field(description="Идентификатор сообщения")
    message: str = Field(description="Текст сообщения")
    message_type: MessageType = Field(description="Тип сообщения")
    documents: list[AbridgedSearchDoc] = Field(description="Связанные документы")
    feedback_type: QAFeedbackType | None = Field(description="Тип фидбека (лайк/дизлайк)")
    feedback_text: str | None = Field(description="Текст фидбека")
    time_created: datetime = Field(description="Время создания сообщения")

    @classmethod
    def build(cls, message: ChatMessage) -> "MessageSnapshot":
        # Подготовка документов
        document_snapshots = []
        for document in message.search_docs:
            doc_snapshot = AbridgedSearchDoc(
                document_id=document.document_id,
                semantic_identifier=document.semantic_id,
                link=document.link,
            )
            document_snapshots.append(doc_snapshot)

        # Обработка фидбека
        latest_feedback = None
        if message.chat_message_feedbacks:
            latest_feedback = message.chat_message_feedbacks[-1]

        # Определение типа фидбека
        feedback_type_value = None
        feedback_text_value = None

        if latest_feedback:
            if latest_feedback.is_positive:
                feedback_type_value = QAFeedbackType.LIKE
            else:
                feedback_type_value = QAFeedbackType.DISLIKE

            feedback_text_value = latest_feedback.feedback_text

        return cls(
            id=message.id,
            message=message.message,
            message_type=message.message_type,
            documents=document_snapshots,
            feedback_type=feedback_type_value,
            feedback_text=feedback_text_value,
            time_created=message.time_sent,
        )


class ChatSessionMinimal(BaseModel):
    id: UUID = Field(
        description="Уникальный идентификатор чат-сессии",
    )
    user_email: str = Field(
        description="Email пользователя (может быть анонимизирован)",
    )
    name: str | None = Field(
        description="Название сессии",
    )
    first_user_message: str = Field(
        description="Первое сообщение пользователя в сессии",
    )
    first_ai_message: str = Field(
        description="Первый ответ ассистента в сессии",
    )
    assistant_id: int | None = Field(
        description="Идентификатор ассистента",
    )
    assistant_name: str | None = Field(
        description="Имя ассистента",
    )
    time_created: datetime = Field(
        description="Время создания сессии",
    )
    feedback_type: QAFeedbackType | None = Field(
        description="Тип фидбека по сессии (лайк/дизлайк/смешанный)",
    )
    flow_type: SessionType = Field(
        description="Тип сессии (чат/Slack)",
    )
    conversation_length: int = Field(
        description="Количество несистемных сообщений в сессии",
    )

    @classmethod
    def from_chat_session(cls, chat_session: ChatSession) -> "ChatSessionMinimal":
        # Подготовка email пользователя
        user_email_value = None
        if chat_session.user:
            user_email_value = chat_session.user.email
        user_email = get_display_email(user_email_value)

        # Поиск первого сообщения пользователя
        first_user_message = ""
        for message in chat_session.messages:
            if message.message_type == MessageType.USER:
                first_user_message = message.message
                break

        # Поиск первого сообщения ассистента
        first_ai_message = ""
        for message in chat_session.messages:
            if message.message_type == MessageType.ASSISTANT:
                first_ai_message = message.message
                break

        # Подготовка имени ассистента
        assistant_name_value = None
        if chat_session.persona:
            assistant_name_value = chat_session.persona.name

        # Сбор всех фидбеков сообщений
        feedback_values = []
        for message in chat_session.messages:
            for feedback in message.chat_message_feedbacks:
                feedback_values.append(feedback.is_positive)

        # Определение типа фидбека для всей сессии
        session_feedback_type = None
        if feedback_values:
            if all(feedback_values):
                session_feedback_type = QAFeedbackType.LIKE
            elif not any(feedback_values):
                session_feedback_type = QAFeedbackType.DISLIKE
            else:
                session_feedback_type = QAFeedbackType.MIXED

        # Определение типа сессии
        if chat_session.onyxbot_flow:
            session_flow_type = SessionType.SLACK
        else:
            session_flow_type = SessionType.CHAT

        # Подсчет длины диалога (без системных сообщений)
        non_system_messages = []
        for message in chat_session.messages:
            if message.message_type != MessageType.SYSTEM:
                non_system_messages.append(message)
        conversation_message_count = len(non_system_messages)

        return cls(
            id=chat_session.id,
            user_email=user_email,
            name=chat_session.description,
            first_user_message=first_user_message,
            first_ai_message=first_ai_message,
            assistant_id=chat_session.persona_id,
            assistant_name=assistant_name_value,
            time_created=chat_session.time_created,
            feedback_type=session_feedback_type,
            flow_type=session_flow_type,
            conversation_length=conversation_message_count,
        )


class ChatSessionSnapshot(BaseModel):
    id: UUID = Field(description="Уникальный идентификатор чат-сессии")
    user_email: str = Field(description="Email пользователя (может быть анонимизирован)")
    name: str | None = Field(description="Название сессии")
    messages: list[MessageSnapshot] = Field(description="Список сообщений сессии")
    assistant_id: int | None = Field(description="Идентификатор ассистента")
    assistant_name: str | None = Field(description="Имя ассистента")
    time_created: datetime = Field(description="Время создания сессии")
    flow_type: SessionType = Field(description="Тип сессии")


class QuestionAnswerPairSnapshot(BaseModel):
    chat_session_id: UUID = Field(description="Идентификатор чат-сессии")
    message_pair_num: int = Field(
        description="Номер пары сообщений в сессии, начиная с 1. "
                    "Первая пара в сессии имеет номер 1, вторая - 2 и т.д."
    )
    user_message: str = Field(description="Вопрос пользователя")
    ai_response: str = Field(description="Ответ ассистента")
    retrieved_documents: list[AbridgedSearchDoc] = Field(description="Документы использованные для ответа")
    feedback_type: QAFeedbackType | None = Field(description="Тип фидбека на ответ")
    feedback_text: str | None = Field(description="Текстовый фидбек")
    persona_name: str | None = Field(description="Название ассистента")
    user_email: str = Field(description="Email пользователя")
    time_created: datetime = Field(description="Время создания пары")
    flow_type: SessionType = Field(description="Тип сессии")


    @classmethod
    def from_chat_session_snapshot(
        cls,
        chat_session_snapshot: ChatSessionSnapshot,
    ) -> list["QuestionAnswerPairSnapshot"]:
        message_pairs: list[tuple[MessageSnapshot, MessageSnapshot]] = []
        message_count = len(chat_session_snapshot.messages)

        for index in range(1, message_count, 2):
            message_pairs.append(
                (
                    chat_session_snapshot.messages[index - 1],
                    chat_session_snapshot.messages[index],
                )
            )

        # Создаем объекты пар
        result_pairs = []
        for pair_index, (user_message, ai_message) in enumerate(message_pairs):
            user_email = get_display_email(
                email=chat_session_snapshot.user_email
            )

            pair = cls(
                chat_session_id=chat_session_snapshot.id,
                message_pair_num=pair_index + 1,
                user_message=user_message.message,
                ai_response=ai_message.message,
                retrieved_documents=ai_message.documents,
                feedback_type=ai_message.feedback_type,
                feedback_text=ai_message.feedback_text,
                persona_name=chat_session_snapshot.assistant_name,
                user_email=user_email,
                time_created=user_message.time_created,
                flow_type=chat_session_snapshot.flow_type,
            )

            result_pairs.append(pair)

        return result_pairs

    def to_json(self) -> dict[str, str | None]:
        """Преобразует объект в словарь для записи в CSV.

        Сериализует сложные поля (документы, enum'ы) в строковое представление,
        подходящее для CSV формата.

        Returns:
            Словарь с сериализованными данными для CSV
        """

        # Формируем строку документов
        documents_string = ""
        if self.retrieved_documents:
            doc_links = []

            for document in self.retrieved_documents:
                if document.link:
                    link = document.link
                else:
                    link = document.semantic_identifier

                doc_links.append(link)

            documents_string = "|".join(doc_links)

        # Подготавливаем значения для CSV
        feedback_type_string = ""
        if self.feedback_type:
            feedback_type_string = self.feedback_type.value

        feedback_text_string = ""
        if self.feedback_text:
            feedback_text_string = self.feedback_text

        return {
            "chat_session_id": str(self.chat_session_id),
            "message_pair_num": str(self.message_pair_num),
            "user_message": self.user_message,
            "ai_response": self.ai_response,
            "retrieved_documents": documents_string,
            "feedback_type": feedback_type_string,
            "feedback_text": feedback_text_string,
            "persona_name": self.persona_name,
            "user_email": self.user_email,
            "time_created": str(self.time_created),
            "flow_type": self.flow_type,
        }
