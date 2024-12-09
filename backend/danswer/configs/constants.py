import platform
import socket
from enum import auto
from enum import Enum

SOURCE_TYPE = "source_type"
# stored in the `metadata` of a chunk. Used to signify that this chunk should
# not be used for QA. For example, Google Drive file types which can't be parsed
# are still useful as a search result but not for QA.
IGNORE_FOR_QA = "ignore_for_qa"
# NOTE: deprecated, only used for porting key from old system
GEN_AI_API_KEY_STORAGE_KEY = "genai_api_key"
PUBLIC_DOC_PAT = "PUBLIC"
ID_SEPARATOR = ":;:"
DEFAULT_BOOST = 0
SESSION_KEY = "session"

# For chunking/processing chunks
RETURN_SEPARATOR = "\n\r\n"
SECTION_SEPARATOR = "\n\n"
# For combining attributes, doesn't have to be unique/perfect to work
INDEX_SEPARATOR = "==="

# For File Connector Metadata override file
DANSWER_METADATA_FILENAME = ".danswer_metadata.json"

# Messages
DISABLED_GEN_AI_MSG = (
    "Your System Admin has disabled the Generative AI functionalities of Danswer.\n"
    "Please contact them if you wish to have this enabled.\n"
    "You can still use Danswer as a search engine."
)

# Postgres connection constants for application_name
POSTGRES_WEB_APP_NAME = "web"
POSTGRES_INDEXER_APP_NAME = "indexer"
POSTGRES_CELERY_APP_NAME = "celery"
POSTGRES_CELERY_BEAT_APP_NAME = "celery_beat"
POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME = "celery_worker_primary"
POSTGRES_CELERY_WORKER_LIGHT_APP_NAME = "celery_worker_light"
POSTGRES_CELERY_WORKER_HEAVY_APP_NAME = "celery_worker_heavy"
POSTGRES_CELERY_WORKER_INDEXING_APP_NAME = "celery_worker_indexing"
POSTGRES_CELERY_WORKER_INDEXING_CHILD_APP_NAME = "celery_worker_indexing_child"
POSTGRES_PERMISSIONS_APP_NAME = "permissions"
POSTGRES_UNKNOWN_APP_NAME = "unknown"

# API Keys
DANSWER_API_KEY_PREFIX = "API_KEY__"
DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN = "danswerapikey.ai"
UNNAMED_KEY_PLACEHOLDER = "Unnamed"

# Key-Value store keys
KV_REINDEX_KEY = "needs_reindexing"
KV_SEARCH_SETTINGS = "search_settings"
KV_UNSTRUCTURED_API_KEY = "unstructured_api_key"
KV_USER_STORE_KEY = "INVITED_USERS"
KV_NO_AUTH_USER_PREFERENCES_KEY = "no_auth_user_preferences"
KV_CRED_KEY = "credential_id_{}"
KV_GMAIL_CRED_KEY = "gmail_app_credential"
KV_GMAIL_SERVICE_ACCOUNT_KEY = "gmail_service_account_key"
KV_GOOGLE_DRIVE_CRED_KEY = "google_drive_app_credential"
KV_GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY = "google_drive_service_account_key"
KV_GEN_AI_KEY_CHECK_TIME = "genai_api_key_last_check_time"
KV_SETTINGS_KEY = "danswer_settings"
KV_CUSTOMER_UUID_KEY = "customer_uuid"
KV_INSTANCE_DOMAIN_KEY = "instance_domain"
KV_ENTERPRISE_SETTINGS_KEY = "danswer_enterprise_settings"
KV_CUSTOM_ANALYTICS_SCRIPT_KEY = "__custom_analytics_script__"
KV_DOCUMENTS_SEEDED_KEY = "documents_seeded"

CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT = 60
CELERY_PRIMARY_WORKER_LOCK_TIMEOUT = 120

# needs to be long enough to cover the maximum time it takes to download an object
# if we can get callbacks as object bytes download, we could lower this a lot.
CELERY_INDEXING_LOCK_TIMEOUT = 3 * 60 * 60  # 60 min

# needs to be long enough to cover the maximum time it takes to download an object
# if we can get callbacks as object bytes download, we could lower this a lot.
CELERY_PRUNING_LOCK_TIMEOUT = 300  # 5 min

CELERY_PERMISSIONS_SYNC_LOCK_TIMEOUT = 300  # 5 min

CELERY_EXTERNAL_GROUP_SYNC_LOCK_TIMEOUT = 300  # 5 min

DANSWER_REDIS_FUNCTION_LOCK_PREFIX = "da_function_lock:"


class DocumentSource(str, Enum):
    # Special case, document passed in via Danswer APIs without specifying a source type
    INGESTION_API = "ingestion_api"
    SLACK = "slack"
    WEB = "web"
    GOOGLE_DRIVE = "google_drive"
    GMAIL = "gmail"
    REQUESTTRACKER = "requesttracker"
    GITHUB = "github"
    GITLAB = "gitlab"
    GURU = "guru"
    BOOKSTACK = "bookstack"
    CONFLUENCE = "confluence"
    SLAB = "slab"
    JIRA = "jira"
    PRODUCTBOARD = "productboard"
    FILE = "file"
    NOTION = "notion"
    ZULIP = "zulip"
    LINEAR = "linear"
    HUBSPOT = "hubspot"
    DOCUMENT360 = "document360"
    GONG = "gong"
    GOOGLE_SITES = "google_sites"
    ZENDESK = "zendesk"
    LOOPIO = "loopio"
    DROPBOX = "dropbox"
    SHAREPOINT = "sharepoint"
    TEAMS = "teams"
    SALESFORCE = "salesforce"
    DISCOURSE = "discourse"
    AXERO = "axero"
    CLICKUP = "clickup"
    MEDIAWIKI = "mediawiki"
    WIKIPEDIA = "wikipedia"
    ASANA = "asana"
    S3 = "s3"
    R2 = "r2"
    GOOGLE_CLOUD_STORAGE = "google_cloud_storage"
    OCI_STORAGE = "oci_storage"
    XENFORO = "xenforo"
    NOT_APPLICABLE = "not_applicable"
    FRESHDESK = "freshdesk"
    FIREFLIES = "fireflies"


DocumentSourceRequiringTenantContext: list[DocumentSource] = [DocumentSource.FILE]


class NotificationType(str, Enum):
    REINDEX = "reindex"
    PERSONA_SHARED = "persona_shared"
    TRIAL_ENDS_TWO_DAYS = "two_day_trial_ending"  # 2 days left in trial


class BlobType(str, Enum):
    R2 = "r2"
    S3 = "s3"
    GOOGLE_CLOUD_STORAGE = "google_cloud_storage"
    OCI_STORAGE = "oci_storage"

    # Special case, for internet search
    NOT_APPLICABLE = "not_applicable"


class DocumentIndexType(str, Enum):
    COMBINED = "combined"  # Vespa
    SPLIT = "split"  # Typesense + Qdrant


class AuthType(str, Enum):
    DISABLED = "disabled"
    BASIC = "basic"
    GOOGLE_OAUTH = "google_oauth"
    OIDC = "oidc"
    SAML = "saml"

    # google auth and basic
    CLOUD = "cloud"


class SessionType(str, Enum):
    CHAT = "Chat"
    SEARCH = "Search"
    SLACK = "Slack"


class QAFeedbackType(str, Enum):
    LIKE = "like"  # User likes the answer, used for metrics
    DISLIKE = "dislike"  # User dislikes the answer, used for metrics


class SearchFeedbackType(str, Enum):
    ENDORSE = "endorse"  # boost this document for all future queries
    REJECT = "reject"  # down-boost this document for all future queries
    HIDE = "hide"  # mark this document as untrusted, hide from LLM
    UNHIDE = "unhide"


class MessageType(str, Enum):
    # Using OpenAI standards, Langchain equivalent shown in comment
    # System message is always constructed on the fly, not saved
    SYSTEM = "system"  # SystemMessage
    USER = "user"  # HumanMessage
    ASSISTANT = "assistant"  # AIMessage


class TokenRateLimitScope(str, Enum):
    USER = "user"
    USER_GROUP = "user_group"
    GLOBAL = "global"


class FileOrigin(str, Enum):
    CHAT_UPLOAD = "chat_upload"
    CHAT_IMAGE_GEN = "chat_image_gen"
    CONNECTOR = "connector"
    GENERATED_REPORT = "generated_report"
    OTHER = "other"


class PostgresAdvisoryLocks(Enum):
    KOMBU_MESSAGE_CLEANUP_LOCK_ID = auto()


class DanswerCeleryQueues:
    # Light queue
    VESPA_METADATA_SYNC = "vespa_metadata_sync"
    DOC_PERMISSIONS_UPSERT = "doc_permissions_upsert"
    CONNECTOR_DELETION = "connector_deletion"

    # Heavy queue
    CONNECTOR_PRUNING = "connector_pruning"
    CONNECTOR_DOC_PERMISSIONS_SYNC = "connector_doc_permissions_sync"
    CONNECTOR_EXTERNAL_GROUP_SYNC = "connector_external_group_sync"

    # Indexing queue
    CONNECTOR_INDEXING = "connector_indexing"


class DanswerRedisLocks:
    PRIMARY_WORKER = "da_lock:primary_worker"
    CHECK_VESPA_SYNC_BEAT_LOCK = "da_lock:check_vespa_sync_beat"
    CHECK_CONNECTOR_DELETION_BEAT_LOCK = "da_lock:check_connector_deletion_beat"
    CHECK_PRUNE_BEAT_LOCK = "da_lock:check_prune_beat"
    CHECK_INDEXING_BEAT_LOCK = "da_lock:check_indexing_beat"
    CHECK_CONNECTOR_DOC_PERMISSIONS_SYNC_BEAT_LOCK = (
        "da_lock:check_connector_doc_permissions_sync_beat"
    )
    CHECK_CONNECTOR_EXTERNAL_GROUP_SYNC_BEAT_LOCK = (
        "da_lock:check_connector_external_group_sync_beat"
    )
    MONITOR_VESPA_SYNC_BEAT_LOCK = "da_lock:monitor_vespa_sync_beat"

    CONNECTOR_DOC_PERMISSIONS_SYNC_LOCK_PREFIX = (
        "da_lock:connector_doc_permissions_sync"
    )
    CONNECTOR_EXTERNAL_GROUP_SYNC_LOCK_PREFIX = "da_lock:connector_external_group_sync"
    PRUNING_LOCK_PREFIX = "da_lock:pruning"
    INDEXING_METADATA_PREFIX = "da_metadata:indexing"

    SLACK_BOT_LOCK = "da_lock:slack_bot"
    SLACK_BOT_HEARTBEAT_PREFIX = "da_heartbeat:slack_bot"


class DanswerCeleryPriority(int, Enum):
    HIGHEST = 0
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()
    LOWEST = auto()


REDIS_SOCKET_KEEPALIVE_OPTIONS = {}
REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPINTVL] = 15
REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPCNT] = 3

if platform.system() == "Darwin":
    REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPALIVE] = 60  # type: ignore
else:
    REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPIDLE] = 60  # type: ignore
