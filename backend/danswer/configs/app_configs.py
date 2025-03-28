import json
import os
import urllib.parse

from danswer.configs.constants import AuthType
from danswer.configs.constants import DocumentIndexType
from danswer.file_processing.enums import HtmlBasedConnectorTransformLinksStrategy

#####
# App Configs
#####
APP_HOST = "0.0.0.0"
APP_PORT = 8080
# API_PREFIX is used to prepend a base path for all API routes
# generally used if using a reverse proxy which doesn't support stripping the `/api`
# prefix from requests directed towards the API server. In these cases, set this to `/api`
APP_API_PREFIX = os.environ.get("API_PREFIX", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT") or "PROD"

#####
# User Facing Features Configs
#####
BLURB_SIZE = 128  # Number Encoder Tokens included in the chunk blurb
GENERATIVE_MODEL_ACCESS_CHECK_FREQ = int(
    os.environ.get("GENERATIVE_MODEL_ACCESS_CHECK_FREQ") or 86400
)  # 1 day
DISABLE_GENERATIVE_AI = os.environ.get("DISABLE_GENERATIVE_AI", "").lower() == "true"


#####
# Web Configs
#####
# WEB_DOMAIN is used to set the redirect_uri after login flows
# NOTE: if you are having problems accessing the Danswer web UI locally (especially
# on Windows, try  setting this to `http://127.0.0.1:3000` instead and see if that
# fixes it)
WEB_DOMAIN = os.environ.get("WEB_DOMAIN") or "http://localhost:3000"


#####
# Auth Configs
#####
AUTH_TYPE = AuthType((os.environ.get("AUTH_TYPE") or AuthType.DISABLED.value).lower())
DISABLE_AUTH = AUTH_TYPE == AuthType.DISABLED

# Encryption key secret is used to encrypt connector credentials, api keys, and other sensitive
# information. This provides an extra layer of security on top of Postgres access controls
# and is available in Danswer EE
ENCRYPTION_KEY_SECRET = os.environ.get("ENCRYPTION_KEY_SECRET") or ""

# Turn off mask if admin users should see full credentials for data connectors.
MASK_CREDENTIAL_PREFIX = (
    os.environ.get("MASK_CREDENTIAL_PREFIX", "True").lower() != "false"
)


SESSION_EXPIRE_TIME_SECONDS = int(
    os.environ.get("SESSION_EXPIRE_TIME_SECONDS") or 86400 * 7
)  # 7 days

# set `VALID_EMAIL_DOMAINS` to a comma seperated list of domains in order to
# restrict access to Danswer to only users with emails from those domains.
# E.g. `VALID_EMAIL_DOMAINS=example.com,example.org` will restrict Danswer
# signups to users with either an @example.com or an @example.org email.
# NOTE: maintaining `VALID_EMAIL_DOMAIN` to keep backwards compatibility
_VALID_EMAIL_DOMAIN = os.environ.get("VALID_EMAIL_DOMAIN", "")
_VALID_EMAIL_DOMAINS_STR = (
    os.environ.get("VALID_EMAIL_DOMAINS", "") or _VALID_EMAIL_DOMAIN
)
VALID_EMAIL_DOMAINS = (
    [domain.strip() for domain in _VALID_EMAIL_DOMAINS_STR.split(",")]
    if _VALID_EMAIL_DOMAINS_STR
    else []
)
# OAuth Login Flow
# Used for both Google OAuth2 and OIDC flows
OAUTH_CLIENT_ID = (
    os.environ.get("OAUTH_CLIENT_ID", os.environ.get("GOOGLE_OAUTH_CLIENT_ID")) or ""
)
OAUTH_CLIENT_SECRET = (
    os.environ.get("OAUTH_CLIENT_SECRET", os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    or ""
)

USER_AUTH_SECRET = os.environ.get("USER_AUTH_SECRET", "")
# for basic auth
REQUIRE_EMAIL_VERIFICATION = (
    os.environ.get("REQUIRE_EMAIL_VERIFICATION", "").lower() == "true"
)
SMTP_SERVER = os.environ.get("SMTP_SERVER") or "smtp.gmail.com"
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "your-email@gmail.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "your-gmail-password")
EMAIL_FROM = os.environ.get("EMAIL_FROM") or SMTP_USER


#####
# DB Configs
#####
DOCUMENT_INDEX_NAME = "danswer_index"
# Vespa is now the default document index store for both keyword and vector
DOCUMENT_INDEX_TYPE = os.environ.get(
    "DOCUMENT_INDEX_TYPE", DocumentIndexType.COMBINED.value
)
VESPA_HOST = os.environ.get("VESPA_HOST") or "localhost"
VESPA_FEED_HOST = os.environ.get("VESPA_FEED_HOST") or "localhost"
# NOTE: this is used if and only if the vespa config server is accessible via a
# different host than the main vespa application
VESPA_CONFIG_SERVER_HOST = os.environ.get("VESPA_CONFIG_SERVER_HOST") or VESPA_HOST
VESPA_PORT = os.environ.get("VESPA_PORT") or "8081"
VESPA_FEED_PORT = os.environ.get("VESPA_FEED_PORT") or "8080"
VESPA_TENANT_PORT = os.environ.get("VESPA_TENANT_PORT") or "19071"
# The default below is for dockerized deployment
VESPA_DEPLOYMENT_ZIP = (
    os.environ.get("VESPA_DEPLOYMENT_ZIP") or "/app/danswer/vespa-app.zip"
)
# Number of documents in a batch during indexing (further batching done by chunks before passing to bi-encoder)
try:
    INDEX_BATCH_SIZE = int(os.environ.get("INDEX_BATCH_SIZE", 16))
except ValueError:
    INDEX_BATCH_SIZE = 16

# Below are intended to match the env variables names used by the official postgres docker image
# https://hub.docker.com/_/postgres
POSTGRES_USER = os.environ.get("POSTGRES_USER") or "postgres"
# URL-encode the password for asyncpg to avoid issues with special characters on some machines.
POSTGRES_PASSWORD = urllib.parse.quote_plus(
    os.environ.get("POSTGRES_PASSWORD") or "password"
)
POSTGRES_HOST = os.environ.get("POSTGRES_HOST") or "localhost"
POSTGRES_PORT = os.environ.get("POSTGRES_PORT") or "5432"
POSTGRES_DB = os.environ.get("POSTGRES_DB") or "postgres"


#####
# Connector Configs
#####
POLL_CONNECTOR_OFFSET = 30  # Minutes overlap between poll windows

# View the list here:
# https://github.com/danswer-ai/danswer/blob/main/backend/danswer/connectors/factory.py
# If this is empty, all connectors are enabled, this is an option for security heavy orgs where
# only very select connectors are enabled and admins cannot add other connector types
ENABLED_CONNECTOR_TYPES = os.environ.get("ENABLED_CONNECTOR_TYPES") or ""

# Some calls to get information on expert users are quite costly especially with rate limiting
# Since experts are not used in the actual user experience, currently it is turned off
# for some connectors
ENABLE_EXPENSIVE_EXPERT_CALLS = False

GOOGLE_DRIVE_INCLUDE_SHARED = False
GOOGLE_DRIVE_FOLLOW_SHORTCUTS = False
GOOGLE_DRIVE_ONLY_ORG_PUBLIC = False

# TODO these should be available for frontend configuration, via advanced options expandable
WEB_CONNECTOR_IGNORED_CLASSES = os.environ.get(
    "WEB_CONNECTOR_IGNORED_CLASSES", "sidebar,footer"
).split(",")
WEB_CONNECTOR_IGNORED_ELEMENTS = os.environ.get(
    "WEB_CONNECTOR_IGNORED_ELEMENTS", "nav,footer,meta,script,style,symbol,aside"
).split(",")
WEB_CONNECTOR_OAUTH_CLIENT_ID = os.environ.get("WEB_CONNECTOR_OAUTH_CLIENT_ID")
WEB_CONNECTOR_OAUTH_CLIENT_SECRET = os.environ.get("WEB_CONNECTOR_OAUTH_CLIENT_SECRET")
WEB_CONNECTOR_OAUTH_TOKEN_URL = os.environ.get("WEB_CONNECTOR_OAUTH_TOKEN_URL")
WEB_CONNECTOR_VALIDATE_URLS = os.environ.get("WEB_CONNECTOR_VALIDATE_URLS")

HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY = os.environ.get(
    "HTML_BASED_CONNECTOR_TRANSFORM_LINKS_STRATEGY",
    HtmlBasedConnectorTransformLinksStrategy.STRIP,
)

NOTION_CONNECTOR_ENABLE_RECURSIVE_PAGE_LOOKUP = (
    os.environ.get("NOTION_CONNECTOR_ENABLE_RECURSIVE_PAGE_LOOKUP", "").lower()
    == "true"
)

CONFLUENCE_CONNECTOR_LABELS_TO_SKIP = [
    ignored_tag
    for ignored_tag in os.environ.get("CONFLUENCE_CONNECTOR_LABELS_TO_SKIP", "").split(
        ","
    )
    if ignored_tag
]

# Avoid to get archived pages
CONFLUENCE_CONNECTOR_INDEX_ONLY_ACTIVE_PAGES = (
    os.environ.get("CONFLUENCE_CONNECTOR_INDEX_ONLY_ACTIVE_PAGES", "").lower() == "true"
)

# Save pages labels as Danswer metadata tags
# The reason to skip this would be to reduce the number of calls to Confluence due to rate limit concerns
CONFLUENCE_CONNECTOR_SKIP_LABEL_INDEXING = (
    os.environ.get("CONFLUENCE_CONNECTOR_SKIP_LABEL_INDEXING", "").lower() == "true"
)

JIRA_CONNECTOR_LABELS_TO_SKIP = [
    ignored_tag
    for ignored_tag in os.environ.get("JIRA_CONNECTOR_LABELS_TO_SKIP", "").split(",")
    if ignored_tag
]
# Maximum size for Jira tickets in bytes (default: 100KB)
JIRA_CONNECTOR_MAX_TICKET_SIZE = int(
    os.environ.get("JIRA_CONNECTOR_MAX_TICKET_SIZE", 100 * 1024)
)

GONG_CONNECTOR_START_TIME = os.environ.get("GONG_CONNECTOR_START_TIME")

GITHUB_CONNECTOR_BASE_URL = os.environ.get("GITHUB_CONNECTOR_BASE_URL") or None

GITLAB_CONNECTOR_INCLUDE_CODE_FILES = (
    os.environ.get("GITLAB_CONNECTOR_INCLUDE_CODE_FILES", "").lower() == "true"
)

DASK_JOB_CLIENT_ENABLED = (
    os.environ.get("DASK_JOB_CLIENT_ENABLED", "").lower() == "true"
)
EXPERIMENTAL_CHECKPOINTING_ENABLED = (
    os.environ.get("EXPERIMENTAL_CHECKPOINTING_ENABLED", "").lower() == "true"
)

DEFAULT_PRUNING_FREQ = 60 * 60 * 24  # Once a day

PREVENT_SIMULTANEOUS_PRUNING = (
    os.environ.get("PREVENT_SIMULTANEOUS_PRUNING", "").lower() == "true"
)

# This is the maxiumum rate at which documents are queried for a pruning job. 0 disables the limitation.
MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE = int(
    os.environ.get("MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE", 0)
)


#####
# Indexing Configs
#####
# NOTE: Currently only supported in the Confluence and Google Drive connectors +
# only handles some failures (Confluence = handles API call failures, Google
# Drive = handles failures pulling files / parsing them)
CONTINUE_ON_CONNECTOR_FAILURE = os.environ.get(
    "CONTINUE_ON_CONNECTOR_FAILURE", ""
).lower() not in ["false", ""]
# When swapping to a new embedding model, a secondary index is created in the background, to conserve
# resources, we pause updates on the primary index by default while the secondary index is created
DISABLE_INDEX_UPDATE_ON_SWAP = (
    os.environ.get("DISABLE_INDEX_UPDATE_ON_SWAP", "").lower() == "true"
)
# Controls how many worker processes we spin up to index documents in the
# background. This is useful for speeding up indexing, but does require a
# fairly large amount of memory in order to increase substantially, since
# each worker loads the embedding models into memory.
NUM_INDEXING_WORKERS = int(os.environ.get("NUM_INDEXING_WORKERS") or 1)
CHUNK_OVERLAP = 0
# More accurate results at the expense of indexing speed and index size (stores additional 4 MINI_CHUNK vectors)
ENABLE_MINI_CHUNK = os.environ.get("ENABLE_MINI_CHUNK", "").lower() == "true"
# Finer grained chunking for more detail retention
# Slightly larger since the sentence aware split is a max cutoff so most minichunks will be under MINI_CHUNK_SIZE
# tokens. But we need it to be at least as big as 1/4th chunk size to avoid having a tiny mini-chunk at the end
MINI_CHUNK_SIZE = 150
# Timeout to wait for job's last update before killing it, in hours
CLEANUP_INDEXING_JOBS_TIMEOUT = int(os.environ.get("CLEANUP_INDEXING_JOBS_TIMEOUT", 3))


#####
# Miscellaneous
#####
# File based Key Value store no longer used
DYNAMIC_CONFIG_STORE = "PostgresBackedDynamicConfigStore"

JOB_TIMEOUT = 60 * 60 * 6  # 6 hours default
# used to allow the background indexing jobs to use a different embedding
# model server than the API server
CURRENT_PROCESS_IS_AN_INDEXING_JOB = (
    os.environ.get("CURRENT_PROCESS_IS_AN_INDEXING_JOB", "").lower() == "true"
)
# Logs every model prompt and output, mostly used for development or exploration purposes
LOG_ALL_MODEL_INTERACTIONS = (
    os.environ.get("LOG_ALL_MODEL_INTERACTIONS", "").lower() == "true"
)
# If set to `true` will enable additional logs about Vespa query performance
# (time spent on finding the right docs + time spent fetching summaries from disk)
LOG_VESPA_TIMING_INFORMATION = (
    os.environ.get("LOG_VESPA_TIMING_INFORMATION", "").lower() == "true"
)
LOG_ENDPOINT_LATENCY = os.environ.get("LOG_ENDPOINT_LATENCY", "").lower() == "true"
# Anonymous usage telemetry
DISABLE_TELEMETRY = os.environ.get("DISABLE_TELEMETRY", "").lower() == "true"

TOKEN_BUDGET_GLOBALLY_ENABLED = (
    os.environ.get("TOKEN_BUDGET_GLOBALLY_ENABLED", "").lower() == "true"
)

# Defined custom query/answer conditions to validate the query and the LLM answer.
# Format: list of strings
CUSTOM_ANSWER_VALIDITY_CONDITIONS = json.loads(
    os.environ.get("CUSTOM_ANSWER_VALIDITY_CONDITIONS", "[]")
)


#####
# Enterprise Edition Configs
#####
# NOTE: this should only be enabled if you have purchased an enterprise license.
# if you're interested in an enterprise license, please reach out to us at
# founders@danswer.ai OR message Chris Weaver or Yuhong Sun in the Danswer
# Slack community (https://join.slack.com/t/danswer/shared_invite/zt-1w76msxmd-HJHLe3KNFIAIzk_0dSOKaQ)
ENTERPRISE_EDITION_ENABLED = (
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() == "true"
)
