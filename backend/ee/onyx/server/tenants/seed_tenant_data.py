"""
Seed data for fast tenant provisioning.

When using metadata.create_all() instead of running Alembic migrations,
the database tables are created but empty. This module inserts the default
seed data that various migrations would have inserted.

IMPORTANT: If you add an Alembic migration that INSERTs default/seed data
into tables, you MUST also update seed_tenant_defaults() here. The parity
test in test_fast_provision_parity.py will catch drift.
"""

import json
import logging
from datetime import datetime
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from onyx.configs.constants import DocumentSource
from onyx.configs.model_configs import ASYM_PASSAGE_PREFIX
from onyx.configs.model_configs import ASYM_QUERY_PREFIX
from onyx.configs.model_configs import DOC_EMBEDDING_DIM
from onyx.configs.model_configs import DOCUMENT_ENCODER_MODEL
from onyx.configs.model_configs import NORMALIZE_EMBEDDINGS
from onyx.configs.model_configs import OLD_DEFAULT_DOCUMENT_ENCODER_MODEL
from onyx.configs.model_configs import OLD_DEFAULT_MODEL_DOC_EMBEDDING_DIM
from onyx.configs.model_configs import OLD_DEFAULT_MODEL_NORMALIZE_EMBEDDINGS
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import SwitchoverType
from onyx.db.models import IndexModelStatus
from onyx.db.search_settings import user_has_overridden_embedding_model
from onyx.natural_language_processing.search_nlp_models import clean_model_name

logger = logging.getLogger(__name__)


# ── Tool definitions ────────────────────────────────────────────────────────
# Mirrors the final state after all tool-seeding migrations have run.
BUILT_IN_TOOLS: list[dict[str, object]] = [
    {
        "name": "internal_search",
        "display_name": "Internal Search",
        "description": (
            "The Search Action allows the agent to search through "
            "connected knowledge to help build an answer."
        ),
        "in_code_tool_id": "SearchTool",
        "enabled": True,
    },
    {
        "name": "generate_image",
        "display_name": "Image Generation",
        "description": (
            "The Image Generation Action allows the agent to use "
            "DALL-E 3 or GPT-IMAGE-1 to generate images. The action will "
            "be used when the user asks the agent to generate an image."
        ),
        "in_code_tool_id": "ImageGenerationTool",
        "enabled": True,
    },
    {
        "name": "web_search",
        "display_name": "Web Search",
        "description": (
            "The Web Search Action allows the agent to perform "
            "internet searches for up-to-date information."
        ),
        "in_code_tool_id": "WebSearchTool",
        "enabled": True,
    },
    {
        "name": "run_kg_search",
        "display_name": "Knowledge Graph Search",
        "description": (
            "The Knowledge Graph Search Action allows the agent to "
            "search the Knowledge Graph for information. This tool can "
            "(for now) only be active in the KG Beta Agent, and it "
            "requires the Knowledge Graph to be enabled."
        ),
        "in_code_tool_id": "KnowledgeGraphTool",
        "enabled": True,
    },
    {
        "name": "OktaProfileTool",
        "display_name": "Okta Profile",
        "description": (
            "The Okta Profile Action allows the agent to fetch the "
            "current user's information from Okta. This may include the "
            "user's name, email, phone number, address, and other details "
            "such as their manager and direct reports."
        ),
        "in_code_tool_id": "OktaProfileTool",
        "enabled": True,
    },
    {
        "name": "read_file",
        "display_name": "File Reader",
        "description": (
            "Read sections of user-uploaded files by character offset. "
            "Useful for inspecting large files that cannot fit entirely "
            "in context."
        ),
        "in_code_tool_id": "FileReaderTool",
        "enabled": True,
    },
    {
        "name": "MemoryTool",
        "display_name": "Add Memory",
        "description": "Save memories about the user for future conversations.",
        "in_code_tool_id": "MemoryTool",
        "enabled": True,
    },
    {
        "name": "python",
        "display_name": "Code Interpreter",
        "description": (
            "The Code Interpreter Action allows the assistant to execute "
            "Python code in a secure, isolated environment for data "
            "analysis, computation, visualization, and file processing."
        ),
        "in_code_tool_id": "PythonTool",
        "enabled": True,
    },
    {
        "name": "open_url",
        "display_name": "Open URL",
        "description": (
            "The Open URL Action allows the agent to fetch and read "
            "contents of web pages."
        ),
        "in_code_tool_id": "OpenURLTool",
        "enabled": True,
    },
    {
        "name": "research_agent",
        "display_name": "Research Agent",
        "description": (
            "The Research Agent is a sub-agent that conducts research "
            "on a specific topic."
        ),
        "in_code_tool_id": "ResearchAgent",
        "enabled": False,
    },
]

# Tools to attach to the default persona (id=0)
_DEFAULT_PERSONA_TOOL_IDS = {
    "SearchTool",
    "ImageGenerationTool",
    "WebSearchTool",
    "FileReaderTool",
    "PythonTool",
    "OpenURLTool",
}

# ── Default persona (Assistant) ────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = """You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the \
user's intent, ask clarifying questions when needed, think step-by-step through complex problems, \
provide clear and accurate answers, and proactively anticipate helpful follow-up information. Always \
prioritize being truthful, nuanced, insightful, and efficient.
The current date is [[CURRENT_DATETIME]]

You use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make \
your responses more readable and engaging.
You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, \
symbols, etc.: '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline.
For code you prefer to use Markdown and specify the language.
You can use Markdown horizontal rules (---) to separate sections of your responses.
You can use Markdown tables to format your responses for data, lists, and other structured information."""

# ── Hierarchy node display names ───────────────────────────────────────────

SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "ingestion_api": "Ingestion API",
    "slack": "Slack",
    "web": "Web",
    "google_drive": "Google Drive",
    "gmail": "Gmail",
    "requesttracker": "Request Tracker",
    "github": "GitHub",
    "gitbook": "GitBook",
    "gitlab": "GitLab",
    "guru": "Guru",
    "bookstack": "BookStack",
    "outline": "Outline",
    "confluence": "Confluence",
    "jira": "Jira",
    "slab": "Slab",
    "productboard": "Productboard",
    "file": "File",
    "coda": "Coda",
    "notion": "Notion",
    "zulip": "Zulip",
    "linear": "Linear",
    "hubspot": "HubSpot",
    "document360": "Document360",
    "gong": "Gong",
    "google_sites": "Google Sites",
    "zendesk": "Zendesk",
    "loopio": "Loopio",
    "dropbox": "Dropbox",
    "sharepoint": "SharePoint",
    "teams": "Teams",
    "salesforce": "Salesforce",
    "discourse": "Discourse",
    "axero": "Axero",
    "clickup": "ClickUp",
    "mediawiki": "MediaWiki",
    "wikipedia": "Wikipedia",
    "asana": "Asana",
    "s3": "S3",
    "r2": "R2",
    "google_cloud_storage": "Google Cloud Storage",
    "oci_storage": "OCI Storage",
    "xenforo": "XenForo",
    "not_applicable": "Not Applicable",
    "discord": "Discord",
    "freshdesk": "Freshdesk",
    "fireflies": "Fireflies",
    "egnyte": "Egnyte",
    "airtable": "Airtable",
    "highspot": "Highspot",
    "drupal_wiki": "Drupal Wiki",
    "imap": "IMAP",
    "bitbucket": "Bitbucket",
    "testrail": "TestRail",
    "mock_connector": "Mock Connector",
    "user_file": "User File",
}


def seed_tenant_defaults(conn: Connection) -> None:
    """Insert all default/seed data that migrations normally provide.

    Must be called AFTER create_all() has created all tables in the
    tenant's schema and the search_path has been set appropriately.
    """
    _add_extra_columns(conn)
    _seed_search_settings(conn)
    _seed_tools(conn)
    _seed_default_persona(conn)
    _seed_persona_tool_associations(conn)
    _seed_code_interpreter_server(conn)
    _seed_hierarchy_nodes(conn)
    _seed_anonymous_user(conn)
    _seed_kg_config(conn)
    logger.info("Seed data inserted successfully")


def _add_extra_columns(conn: Connection) -> None:
    """Add columns that migrations create via raw SQL (not in models.py).

    These are generated/derived columns that SQLAlchemy models can't
    represent but which the application relies on.
    """
    # tsvector columns for full-text search (from migration 3bd4c84fe72f)
    conn.execute(
        text(
            """
            ALTER TABLE chat_message
            ADD COLUMN IF NOT EXISTS message_tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('english', message)) STORED
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_message_tsv
            ON chat_message USING GIN (message_tsv)
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE chat_session
            ADD COLUMN IF NOT EXISTS description_tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(description, ''))
            ) STORED
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_session_desc_tsv
            ON chat_session USING GIN (description_tsv)
            """
        )
    )


def _seed_search_settings(conn: Connection) -> None:
    """Seed the initial PRESENT and FUTURE search_settings rows.

    Mirrors the logic from migration dbaa756c2ccf_embedding_models.py:
    - PRESENT row uses the old/current embedding model
    - FUTURE row uses the new default model (if not overridden)
    """
    is_overridden = user_has_overridden_embedding_model()

    _SEARCH_SETTINGS_SQL = text(
        """
        INSERT INTO search_settings (
            model_name, model_dim, normalize, query_prefix,
            passage_prefix, status, index_name, embedding_precision,
            switchover_type, multipass_indexing, enable_contextual_rag,
            multilingual_expansion
        ) VALUES (
            :model_name, :model_dim, :normalize, :query_prefix,
            :passage_prefix, :status, :index_name, :embedding_precision,
            :switchover_type, :multipass_indexing, :enable_contextual_rag,
            CAST(:multilingual_expansion AS VARCHAR[])
        )
        """
    )

    # PRESENT row: old/current embedding model
    present_model = (
        DOCUMENT_ENCODER_MODEL if is_overridden else OLD_DEFAULT_DOCUMENT_ENCODER_MODEL
    )
    present_dim = (
        DOC_EMBEDDING_DIM if is_overridden else OLD_DEFAULT_MODEL_DOC_EMBEDDING_DIM
    )
    present_normalize = (
        NORMALIZE_EMBEDDINGS
        if is_overridden
        else OLD_DEFAULT_MODEL_NORMALIZE_EMBEDDINGS
    )
    present_query_prefix = ASYM_QUERY_PREFIX if is_overridden else ""
    present_passage_prefix = ASYM_PASSAGE_PREFIX if is_overridden else ""

    conn.execute(
        _SEARCH_SETTINGS_SQL,
        {
            "model_name": present_model,
            "model_dim": present_dim,
            "normalize": present_normalize,
            "query_prefix": present_query_prefix,
            "passage_prefix": present_passage_prefix,
            "status": IndexModelStatus.PRESENT.name,
            "index_name": "danswer_chunk",
            "embedding_precision": EmbeddingPrecision.FLOAT.name,
            "switchover_type": SwitchoverType.REINDEX.name,
            "multipass_indexing": False,
            "enable_contextual_rag": False,
            "multilingual_expansion": "{}",
        },
    )

    # FUTURE row: new default model (only if user hasn't overridden)
    if not is_overridden:
        future_index = f"danswer_chunk_{clean_model_name(DOCUMENT_ENCODER_MODEL)}"
        conn.execute(
            _SEARCH_SETTINGS_SQL,
            {
                "model_name": DOCUMENT_ENCODER_MODEL,
                "model_dim": DOC_EMBEDDING_DIM,
                "normalize": NORMALIZE_EMBEDDINGS,
                "query_prefix": ASYM_QUERY_PREFIX,
                "passage_prefix": ASYM_PASSAGE_PREFIX,
                "status": IndexModelStatus.FUTURE.name,
                "index_name": future_index,
                "embedding_precision": EmbeddingPrecision.FLOAT.name,
                "switchover_type": SwitchoverType.REINDEX.name,
                "multipass_indexing": False,
                "enable_contextual_rag": False,
                "multilingual_expansion": "{}",
            },
        )


def _seed_tools(conn: Connection) -> None:
    """Insert all built-in tools."""
    for tool in BUILT_IN_TOOLS:
        conn.execute(
            text(
                """
                INSERT INTO tool (
                    name, display_name, description, in_code_tool_id,
                    enabled, passthrough_auth
                )
                VALUES (
                    :name, :display_name, :description, :in_code_tool_id,
                    :enabled, false
                )
                """
            ),
            tool,
        )


def _seed_default_persona(conn: Connection) -> None:
    """Insert the default Assistant persona (id=0)."""
    # Matches migration 505c488f6662: system_prompt is NULL by default,
    # is_featured is True for the default assistant.
    conn.execute(
        text(
            """
            INSERT INTO persona (
                id, name, description,
                builtin_persona, is_public, is_listed, is_featured,
                display_priority, deleted, datetime_aware,
                replace_base_system_prompt
            ) VALUES (
                0, :name, :description,
                true, true, true, true,
                0, false, true,
                false
            )
            """
        ),
        {
            "name": "Assistant",
            "description": (
                "Your AI assistant with search, web browsing, "
                "and image generation capabilities."
            ),
        },
    )


def _seed_persona_tool_associations(conn: Connection) -> None:
    """Link the default persona to its tools."""
    for tool_id in _DEFAULT_PERSONA_TOOL_IDS:
        conn.execute(
            text(
                """
                INSERT INTO persona__tool (persona_id, tool_id)
                SELECT 0, id FROM tool WHERE in_code_tool_id = :in_code_tool_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"in_code_tool_id": tool_id},
        )


def _seed_code_interpreter_server(conn: Connection) -> None:
    """Insert the single code_interpreter_server row."""
    conn.execute(
        text("INSERT INTO code_interpreter_server (server_enabled) VALUES (true)")
    )


def _seed_hierarchy_nodes(conn: Connection) -> None:
    """Insert SOURCE-type hierarchy nodes for every DocumentSource."""
    for source in DocumentSource:
        source_name = source.name  # e.g. 'GOOGLE_DRIVE' (enum storage)
        source_value = source.value  # e.g. 'google_drive' (raw_node_id)
        display_name = SOURCE_DISPLAY_NAMES.get(
            source_value, source_value.replace("_", " ").title()
        )
        conn.execute(
            text(
                """
                INSERT INTO hierarchy_node (
                    raw_node_id, display_name, source, node_type, parent_id, is_public
                ) VALUES (
                    :raw_node_id, :display_name, :source, 'SOURCE', NULL, true
                )
                ON CONFLICT (raw_node_id, source) DO NOTHING
                """
            ),
            {
                "raw_node_id": source_value,
                "display_name": display_name,
                "source": source_name,
            },
        )


def _seed_anonymous_user(conn: Connection) -> None:
    """Insert the anonymous user placeholder."""
    conn.execute(
        text(
            """
            INSERT INTO "user" (
                id, email, hashed_password,
                is_active, is_superuser, is_verified, role,
                shortcut_enabled, temperature_override_enabled,
                default_app_mode, use_memories,
                enable_memory_tool, visible_assistants, hidden_assistants,
                voice_auto_send, voice_auto_playback, voice_playback_speed,
                account_type, effective_permissions
            ) VALUES (
                :id, :email, :hashed_password,
                :is_active, :is_superuser, :is_verified, :role,
                false, false,
                'CHAT', true,
                true, '[]'::jsonb, '[]'::jsonb,
                false, false, 1.0,
                'ANONYMOUS', '[]'::jsonb
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "email": "anonymous@onyx.app",
            "hashed_password": "",
            "is_active": True,
            "is_superuser": False,
            "is_verified": True,
            "role": "LIMITED",
        },
    )


def _seed_kg_config(conn: Connection) -> None:
    """Insert default KG config into key_value_store."""
    # Values match migration 03bf8be6b53a which stores booleans and
    # integers as strings (from the original kg_config table format)
    kg_defaults: dict[str, str | list[str] | None] = {
        "KG_EXPOSED": "false",
        "KG_ENABLED": "false",
        "KG_VENDOR": None,
        "KG_VENDOR_DOMAINS": [],
        "KG_IGNORE_EMAIL_DOMAINS": [],
        "KG_COVERAGE_START": (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
        "KG_MAX_COVERAGE_DAYS": "90",
        "KG_MAX_PARENT_RECURSION_DEPTH": "2",
        "KG_BETA_PERSONA_ID": None,
    }
    conn.execute(
        text("INSERT INTO key_value_store (key, value) VALUES (:key, :value)"),
        {"key": "kg_config", "value": json.dumps(kg_defaults)},
    )
