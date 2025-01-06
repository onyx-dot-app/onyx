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

NO_AUTH_USER_ID = "__no_auth_user__"
NO_AUTH_USER_EMAIL = "anonymous@onyx.app"

# For chunking/processing chunks
RETURN_SEPARATOR = "\n\r\n"
SECTION_SEPARATOR = "\n\n"
# For combining attributes, doesn't have to be unique/perfect to work
INDEX_SEPARATOR = "==="

# For File Connector Metadata override file
DANSWER_METADATA_FILENAME = ".onyx_metadata.json"

# Messages
DISABLED_GEN_AI_MSG = (
    "Your System Admin has disabled the Generative AI functionalities of Onyx.\n"
    "Please contact them if you wish to have this enabled.\n"
    "You can still use Onyx as a search engine."
)

DEFAULT_PERSONA_ID = 0

DEFAULT_CC_PAIR_ID = 1

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

SSL_CERT_FILE = "bundle.pem"
# API Keys
DANSWER_API_KEY_PREFIX = "API_KEY__"
DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN = "onyxapikey.ai"
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
KV_SETTINGS_KEY = "onyx_settings"
KV_CUSTOMER_UUID_KEY = "customer_uuid"
KV_INSTANCE_DOMAIN_KEY = "instance_domain"
KV_ENTERPRISE_SETTINGS_KEY = "onyx_enterprise_settings"
KV_CUSTOM_ANALYTICS_SCRIPT_KEY = "__custom_analytics_script__"
KV_DOCUMENTS_SEEDED_KEY = "documents_seeded"

# NOTE: we use this timeout / 4 in various places to refresh a lock
# might be worth separating this timeout into separate timeouts for each situation
CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT = 120

CELERY_PRIMARY_WORKER_LOCK_TIMEOUT = 120

# needs to be long enough to cover the maximum time it takes to download an object
# if we can get callbacks as object bytes download, we could lower this a lot.
CELERY_INDEXING_LOCK_TIMEOUT = 3 * 60 * 60  # 60 min

# how long a task should wait for associated fence to be ready
CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT = 5 * 60  # 5 min

# needs to be long enough to cover the maximum time it takes to download an object
# if we can get callbacks as object bytes download, we could lower this a lot.
CELERY_PRUNING_LOCK_TIMEOUT = 300  # 5 min

CELERY_PERMISSIONS_SYNC_LOCK_TIMEOUT = 300  # 5 min

CELERY_EXTERNAL_GROUP_SYNC_LOCK_TIMEOUT = 300  # 5 min

DANSWER_REDIS_FUNCTION_LOCK_PREFIX = "da_function_lock:"


class DocumentSource(str, Enum):
    # Special case, document passed in via Onyx APIs without specifying a source type
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
    DISCORD = "discord"
    FRESHDESK = "freshdesk"
    FIREFLIES = "fireflies"
    EGNYTE = "egnyte"
    AIRTABLE = "airtable"


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


# Special characters for password validation
PASSWORD_SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?"


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


class MilestoneRecordType(str, Enum):
    TENANT_CREATED = "tenant_created"
    USER_SIGNED_UP = "user_signed_up"
    MULTIPLE_USERS = "multiple_users"
    VISITED_ADMIN_PAGE = "visited_admin_page"
    CREATED_CONNECTOR = "created_connector"
    CONNECTOR_SUCCEEDED = "connector_succeeded"
    RAN_QUERY = "ran_query"
    MULTIPLE_ASSISTANTS = "multiple_assistants"
    CREATED_ASSISTANT = "created_assistant"
    CREATED_ONYX_BOT = "created_onyx_bot"


class PostgresAdvisoryLocks(Enum):
    KOMBU_MESSAGE_CLEANUP_LOCK_ID = auto()


class OnyxCeleryQueues:
    # Light queue
    VESPA_METADATA_SYNC = "vespa_metadata_sync"
    DOC_PERMISSIONS_UPSERT = "doc_permissions_upsert"
    CONNECTOR_DELETION = "connector_deletion"
    LLM_MODEL_UPDATE = "llm_model_update"

    # Heavy queue
    CONNECTOR_PRUNING = "connector_pruning"
    CONNECTOR_DOC_PERMISSIONS_SYNC = "connector_doc_permissions_sync"
    CONNECTOR_EXTERNAL_GROUP_SYNC = "connector_external_group_sync"

    # Indexing queue
    CONNECTOR_INDEXING = "connector_indexing"


class OnyxRedisLocks:
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
    ANONYMOUS_USER_ENABLED = "anonymous_user_enabled"


class OnyxRedisSignals:
    VALIDATE_INDEXING_FENCES = "signal:validate_indexing_fences"


class OnyxCeleryPriority(int, Enum):
    HIGHEST = 0
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()
    LOWEST = auto()


class OnyxCeleryTask:
    CHECK_FOR_CONNECTOR_DELETION = "check_for_connector_deletion_task"
    CHECK_FOR_VESPA_SYNC_TASK = "check_for_vespa_sync_task"
    CHECK_FOR_INDEXING = "check_for_indexing"
    CHECK_FOR_PRUNING = "check_for_pruning"
    CHECK_FOR_DOC_PERMISSIONS_SYNC = "check_for_doc_permissions_sync"
    CHECK_FOR_EXTERNAL_GROUP_SYNC = "check_for_external_group_sync"
    CHECK_FOR_LLM_MODEL_UPDATE = "check_for_llm_model_update"
    MONITOR_VESPA_SYNC = "monitor_vespa_sync"
    KOMBU_MESSAGE_CLEANUP_TASK = "kombu_message_cleanup_task"
    CONNECTOR_PERMISSION_SYNC_GENERATOR_TASK = (
        "connector_permission_sync_generator_task"
    )
    UPDATE_EXTERNAL_DOCUMENT_PERMISSIONS_TASK = (
        "update_external_document_permissions_task"
    )
    CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK = (
        "connector_external_group_sync_generator_task"
    )
    CONNECTOR_INDEXING_PROXY_TASK = "connector_indexing_proxy_task"
    CONNECTOR_PRUNING_GENERATOR_TASK = "connector_pruning_generator_task"
    DOCUMENT_BY_CC_PAIR_CLEANUP_TASK = "document_by_cc_pair_cleanup_task"
    VESPA_METADATA_SYNC_TASK = "vespa_metadata_sync_task"
    CHECK_TTL_MANAGEMENT_TASK = "check_ttl_management_task"
    AUTOGENERATE_USAGE_REPORT_TASK = "autogenerate_usage_report_task"


REDIS_SOCKET_KEEPALIVE_OPTIONS = {}
REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPINTVL] = 15
REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPCNT] = 3

if platform.system() == "Darwin":
    REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPALIVE] = 60  # type: ignore
else:
    REDIS_SOCKET_KEEPALIVE_OPTIONS[socket.TCP_KEEPIDLE] = 60  # type: ignore
