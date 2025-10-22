from enum import Enum as PyEnum


class IndexingStatus(str, PyEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    CANCELED = "canceled"
    FAILED = "failed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"

    def is_terminal(self) -> bool:
        terminal_states = {
            IndexingStatus.SUCCESS,
            IndexingStatus.COMPLETED_WITH_ERRORS,
            IndexingStatus.CANCELED,
            IndexingStatus.FAILED,
        }
        return self in terminal_states


class IndexingMode(str, PyEnum):
    UPDATE = "update"
    REINDEX = "reindex"


class SyncType(str, PyEnum):
    DOCUMENT_SET = "document_set"
    USER_GROUP = "user_group"
    CONNECTOR_DELETION = "connector_deletion"
    PRUNING = "pruning"  # not really a sync, but close enough
    EXTERNAL_PERMISSIONS = "external_permissions"
    EXTERNAL_GROUP = "external_group"

    def __str__(self) -> str:
        return self.value


class SyncStatus(str, PyEnum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"

    def is_terminal(self) -> bool:
        terminal_states = {
            SyncStatus.SUCCESS,
            SyncStatus.FAILED,
        }
        return self in terminal_states


# Consistent with Celery task statuses
class TaskStatus(str, PyEnum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class IndexModelStatus(str, PyEnum):
    PAST = "PAST"
    PRESENT = "PRESENT"
    FUTURE = "FUTURE"

    def is_current(self) -> bool:
        return self == IndexModelStatus.PRESENT


class ChatSessionSharedStatus(str, PyEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class ConnectorCredentialPairStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETING = "DELETING"
    INVALID = "INVALID"

    def is_active(self) -> bool:
        return self == ConnectorCredentialPairStatus.ACTIVE


class AccessType(str, PyEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    SYNC = "sync"


class EmbeddingPrecision(str, PyEnum):
    # matches vespa tensor type
    # only support float / bfloat16 for now, since there's not a
    # good reason to specify anything else
    BFLOAT16 = "bfloat16"
    FLOAT = "float"


class ValidatorType(str, PyEnum):
    """Типы валидаторов для проверки контента и безопасности.

    - DETECT_PII: Обнаружение персональных данных (Personal Identifiable Information);
    - TOXIC_LANGUAGE: Валидация токсичности контента;
    - NSFW_TEXT: Проверка на неприемлемый для работы контент (Not Safe For Work);
    - SENSITIVE_TOPIC: Валидация запретных и чувствительных тем;
    - BAN_LIST: Проверка на наличие запрещенных слов и оборотов;
    - TEXT_STYLE: Валидация соответствия определённому стилю общения;
    - VALID_LENGTH: Проверка длины контента;
    - VALID_JSON: Валидация JSON-структур и синтаксиса;
    - COMPETITOR_CHECK: Проверка на упоминание конкурентов и ключевых сущностей;
    - HALLUCINATION: Обнаружение галлюцинаций в выводе языковых моделей;
    - TOPIC_RESTRICTION: Классификация и перенаправление запросов по тематикам;
    - JAILBREAKING: Защита от манипулирования и взлома языковых моделей;
    """

    DETECT_PII = "DETECT_PII"
    TOXIC_LANGUAGE = "TOXIC_LANGUAGE"
    NSFW_TEXT = "NSFW_TEXT"
    SENSITIVE_TOPIC = "SENSITIVE_TOPIC"
    BAN_LIST = "BAN_LIST"
    TEXT_STYLE = "TEXT_STYLE"
    VALID_LENGTH = "VALID_LENGTH"
    VALID_JSON = "VALID_JSON"
    COMPETITOR_CHECK = "COMPETITOR_CHECK"
    HALLUCINATION = "HALLUCINATION"
    TOPIC_RESTRICTION = "TOPIC_RESTRICTION"
    JAILBREAKING = "JAILBREAKING"
