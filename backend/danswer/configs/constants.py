from enum import Enum

DOCUMENT_ID = "document_id"
CHUNK_ID = "chunk_id"
BLURB = "blurb"
CONTENT = "content"
SOURCE_TYPE = "source_type"
SOURCE_LINKS = "source_links"
SOURCE_LINK = "link"
SEMANTIC_IDENTIFIER = "semantic_identifier"
TITLE = "title"
SKIP_TITLE_EMBEDDING = "skip_title"
SECTION_CONTINUATION = "section_continuation"
EMBEDDINGS = "embeddings"
TITLE_EMBEDDING = "title_embedding"
ALLOWED_USERS = "allowed_users"
ACCESS_CONTROL_LIST = "access_control_list"
DOCUMENT_SETS = "document_sets"
TIME_FILTER = "time_filter"
METADATA = "metadata"
METADATA_LIST = "metadata_list"
METADATA_SUFFIX = "metadata_suffix"
MATCH_HIGHLIGHTS = "match_highlights"
# stored in the `metadata` of a chunk. Used to signify that this chunk should
# not be used for QA. For example, Google Drive file types which can't be parsed
# are still useful as a search result but not for QA.
IGNORE_FOR_QA = "ignore_for_qa"
# NOTE: deprecated, only used for porting key from old system
GEN_AI_API_KEY_STORAGE_KEY = "genai_api_key"
PUBLIC_DOC_PAT = "PUBLIC"
PUBLIC_DOCUMENT_SET = "__PUBLIC"
QUOTE = "quote"
BOOST = "boost"
DOC_UPDATED_AT = "doc_updated_at"  # Indexed as seconds since epoch
PRIMARY_OWNERS = "primary_owners"
SECONDARY_OWNERS = "secondary_owners"
RECENCY_BIAS = "recency_bias"
HIDDEN = "hidden"
SCORE = "score"
ID_SEPARATOR = ":;:"
DEFAULT_BOOST = 0
SESSION_KEY = "session"
QUERY_EVENT_ID = "query_event_id"
LLM_CHUNKS = "llm_chunks"

# For chunking/processing chunks
MAX_CHUNK_TITLE_LEN = 1000
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


# API Keys
DANSWER_API_KEY_PREFIX = "API_KEY__"
DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN = "danswerapikey.ai"
UNNAMED_KEY_PLACEHOLDER = "Unnamed"


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
    S3 = "s3"
    R2 = "r2"
    GOOGLE_CLOUD_STORAGE = "google_cloud_storage"
    OCI_STORAGE = "oci_storage"
    NOT_APPLICABLE = "not_applicable"


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
