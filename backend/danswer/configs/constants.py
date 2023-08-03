from enum import Enum

ALLOWED_GROUPS = "allowed_groups"
ALLOWED_USERS = "allowed_users"
BLURB = "blurb"
CHUNK_ID = "chunk_id"
CONTENT = "content"
DOCUMENT_ID = "document_id"
HTML_SEPARATOR = "\n"
METADATA = "metadata"
OPENAI_API_KEY_STORAGE_KEY = "openai_api_key"
PUBLIC_DOC_PAT = "PUBLIC"
SECTION_CONTINUATION = "section_continuation"
SEMANTIC_IDENTIFIER = "semantic_identifier"
SOURCE_LINK = "link"
SOURCE_LINKS = "source_links"
SOURCE_TYPE = "source_type"


class DocumentSource(str, Enum):
    AIRTABLE = "airtable"
    BOOKSTACK = "bookstack"
    CONFLUENCE = "confluence"
    FILE = "file"
    GITHUB = "github"
    GOOGLE_DRIVE = "google_drive"
    GURU = "guru"
    JIRA = "jira"
    NOTION = "notion"
    PRODUCTBOARD = "productboard"
    SLAB = "slab"
    SLACK = "slack"
    WEB = "web"
