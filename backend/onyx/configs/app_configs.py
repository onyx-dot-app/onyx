import json
import os
import urllib.parse
from datetime import datetime
from datetime import timezone
from typing import cast

from onyx.auth.schemas import AuthBackend
from onyx.configs.constants import AuthType
from onyx.configs.constants import DocumentIndexType
from onyx.configs.constants import QueryHistoryType
from onyx.file_processing.enums import HtmlBasedConnectorTransformLinksStrategy
from onyx.prompts.image_analysis import DEFAULT_IMAGE_ANALYSIS_SYSTEM_PROMPT
from onyx.prompts.image_analysis import DEFAULT_IMAGE_SUMMARIZATION_SYSTEM_PROMPT
from onyx.prompts.image_analysis import DEFAULT_IMAGE_SUMMARIZATION_USER_PROMPT

#####
# App Configs
#####
APP_HOST = "0.0.0.0"
APP_PORT = 8080
# API_PREFIX is used to prepend a base path for all API routes
# generally used if using a reverse proxy which doesn't support stripping the `/api`
# prefix from requests directed towards the API server. In these cases, set this to `/api`
APP_API_PREFIX = os.environ.get("API_PREFIX", "")

#####
# User Facing Features Configs
#####
BLURB_SIZE = 128  # Number Encoder Tokens included in the chunk blurb
GENERATIVE_MODEL_ACCESS_CHECK_FREQ = int(
    os.environ.get("GENERATIVE_MODEL_ACCESS_CHECK_FREQ") or 86400
)  # 1 day
DISABLE_GENERATIVE_AI = os.environ.get("DISABLE_GENERATIVE_AI", "").lower() == "true"

# Controls whether users can use User Knowledge (personal documents) in assistants
DISABLE_USER_KNOWLEDGE = os.environ.get("DISABLE_USER_KNOWLEDGE", "").lower() == "true"

# If set to true, will show extra/uncommon connectors in the "Other" category
SHOW_EXTRA_CONNECTORS = os.environ.get("SHOW_EXTRA_CONNECTORS", "").lower() == "true"

# Controls whether to allow admin query history reports with:
# 1. associated user emails
# 2. anonymized user emails
# 3. no queries
ONYX_QUERY_HISTORY_TYPE = QueryHistoryType(
    (os.environ.get("ONYX_QUERY_HISTORY_TYPE") or QueryHistoryType.NORMAL.value).lower()
)

#####
# Web Configs
#####
# WEB_DOMAIN is used to set the redirect_uri after login flows
# NOTE: if you are having problems accessing the Onyx web UI locally (especially
# on Windows, try  setting this to `http://127.0.0.1:3000` instead and see if that
# fixes it)
WEB_DOMAIN = os.environ.get("WEB_DOMAIN") or "http://localhost:3000"


#####
# Auth Configs
#####
AUTH_TYPE = AuthType((os.environ.get("AUTH_TYPE") or AuthType.DISABLED.value).lower())
DISABLE_AUTH = AUTH_TYPE == AuthType.DISABLED

PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", 8))
PASSWORD_MAX_LENGTH = int(os.getenv("PASSWORD_MAX_LENGTH", 64))
PASSWORD_REQUIRE_UPPERCASE = (
    os.environ.get("PASSWORD_REQUIRE_UPPERCASE", "false").lower() == "true"
)
PASSWORD_REQUIRE_LOWERCASE = (
    os.environ.get("PASSWORD_REQUIRE_LOWERCASE", "false").lower() == "true"
)
PASSWORD_REQUIRE_DIGIT = (
    os.environ.get("PASSWORD_REQUIRE_DIGIT", "false").lower() == "true"
)
PASSWORD_REQUIRE_SPECIAL_CHAR = (
    os.environ.get("PASSWORD_REQUIRE_SPECIAL_CHAR", "false").lower() == "true"
)

# Encryption key secret is used to encrypt connector credentials, api keys, and other sensitive
# information. This provides an extra layer of security on top of Postgres access controls
# and is available in Onyx EE
ENCRYPTION_KEY_SECRET = os.environ.get("ENCRYPTION_KEY_SECRET") or ""

# Turn off mask if admin users should see full credentials for data connectors.
MASK_CREDENTIAL_PREFIX = (
    os.environ.get("MASK_CREDENTIAL_PREFIX", "True").lower() != "false"
)

AUTH_BACKEND = AuthBackend(os.environ.get("AUTH_BACKEND") or AuthBackend.REDIS.value)

SESSION_EXPIRE_TIME_SECONDS = int(
    os.environ.get("SESSION_EXPIRE_TIME_SECONDS")
    or os.environ.get("REDIS_AUTH_EXPIRE_TIME_SECONDS")
    or 86400 * 7
)  # 7 days

# Default request timeout, mostly used by connectors
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS") or 60)

# set `VALID_EMAIL_DOMAINS` to a comma seperated list of domains in order to
# restrict access to Onyx to only users with emails from those domains.
# E.g. `VALID_EMAIL_DOMAINS=example.com,example.org` will restrict Onyx
# signups to users with either an @example.com or an @example.org email.
# NOTE: maintaining `VALID_EMAIL_DOMAIN` to keep backwards compatibility
_VALID_EMAIL_DOMAIN = os.environ.get("VALID_EMAIL_DOMAIN", "")
_VALID_EMAIL_DOMAINS_STR = (
    os.environ.get("VALID_EMAIL_DOMAINS", "") or _VALID_EMAIL_DOMAIN
)
VALID_EMAIL_DOMAINS = (
    [
        domain.strip().lower()
        for domain in _VALID_EMAIL_DOMAINS_STR.split(",")
        if domain.strip()
    ]
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
# OpenID Connect configuration URL for Okta Profile Tool and other OIDC integrations
OPENID_CONFIG_URL = os.environ.get("OPENID_CONFIG_URL") or ""

# Applicable for OIDC Auth, allows you to override the scopes that
# are requested from the OIDC provider. Currently used when passing
# over access tokens to tool calls and the tool needs more scopes
OIDC_SCOPE_OVERRIDE: list[str] | None = None
_OIDC_SCOPE_OVERRIDE = os.environ.get("OIDC_SCOPE_OVERRIDE")

if _OIDC_SCOPE_OVERRIDE:
    try:
        OIDC_SCOPE_OVERRIDE = [
            scope.strip() for scope in _OIDC_SCOPE_OVERRIDE.split(",")
        ]
    except Exception:
        pass

# Applicable for SAML Auth
SAML_CONF_DIR = os.environ.get("SAML_CONF_DIR") or "/app/onyx/configs/saml_config"

# JWT Public Key URL for JWT token verification
JWT_PUBLIC_KEY_URL: str | None = os.getenv("JWT_PUBLIC_KEY_URL", None)

USER_AUTH_SECRET = os.environ.get("USER_AUTH_SECRET", "")

# Duration (in seconds) for which the FastAPI Users JWT token remains valid in the user's browser.
# By default, this is set to match the Redis expiry time for consistency.
AUTH_COOKIE_EXPIRE_TIME_SECONDS = int(
    os.environ.get("AUTH_COOKIE_EXPIRE_TIME_SECONDS") or 86400 * 7
)  # 7 days

# for basic auth
REQUIRE_EMAIL_VERIFICATION = (
    os.environ.get("REQUIRE_EMAIL_VERIFICATION", "").lower() == "true"
)
SMTP_SERVER = os.environ.get("SMTP_SERVER") or "smtp.gmail.com"
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "your-email@gmail.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "your-gmail-password")
EMAIL_FROM = os.environ.get("EMAIL_FROM") or SMTP_USER

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY") or ""
EMAIL_CONFIGURED = all([SMTP_SERVER, SMTP_USER, SMTP_PASS]) or SENDGRID_API_KEY

# If set, Onyx will listen to the `expires_at` returned by the identity
# provider (e.g. Okta, Google, etc.) and force the user to re-authenticate
# after this time has elapsed. Disabled since by default many auth providers
# have very short expiry times (e.g. 1 hour) which provide a poor user experience
TRACK_EXTERNAL_IDP_EXPIRY = (
    os.environ.get("TRACK_EXTERNAL_IDP_EXPIRY", "").lower() == "true"
)


#####
# DB Configs
#####
DOCUMENT_INDEX_NAME = "danswer_index"
# Vespa is now the default document index store for both keyword and vector
DOCUMENT_INDEX_TYPE = os.environ.get(
    "DOCUMENT_INDEX_TYPE", DocumentIndexType.COMBINED.value
)
VESPA_HOST = os.environ.get("VESPA_HOST") or "localhost"
# NOTE: this is used if and only if the vespa config server is accessible via a
# different host than the main vespa application
VESPA_CONFIG_SERVER_HOST = os.environ.get("VESPA_CONFIG_SERVER_HOST") or VESPA_HOST
VESPA_PORT = os.environ.get("VESPA_PORT") or "8081"
VESPA_TENANT_PORT = os.environ.get("VESPA_TENANT_PORT") or "19071"
# the number of times to try and connect to vespa on startup before giving up
VESPA_NUM_ATTEMPTS_ON_STARTUP = int(os.environ.get("NUM_RETRIES_ON_STARTUP") or 10)

VESPA_CLOUD_URL = os.environ.get("VESPA_CLOUD_URL", "")

# The default below is for dockerized deployment
VESPA_DEPLOYMENT_ZIP = (
    os.environ.get("VESPA_DEPLOYMENT_ZIP") or "/app/onyx/vespa-app.zip"
)
VESPA_CLOUD_CERT_PATH = os.environ.get("VESPA_CLOUD_CERT_PATH")
VESPA_CLOUD_KEY_PATH = os.environ.get("VESPA_CLOUD_KEY_PATH")

# Number of documents in a batch during indexing (further batching done by chunks before passing to bi-encoder)
INDEX_BATCH_SIZE = int(os.environ.get("INDEX_BATCH_SIZE") or 16)

MAX_DRIVE_WORKERS = int(os.environ.get("MAX_DRIVE_WORKERS", 4))

# Below are intended to match the env variables names used by the official postgres docker image
# https://hub.docker.com/_/postgres
POSTGRES_USER = os.environ.get("POSTGRES_USER") or "postgres"
# URL-encode the password for asyncpg to avoid issues with special characters on some machines.
POSTGRES_PASSWORD = urllib.parse.quote_plus(
    os.environ.get("POSTGRES_PASSWORD") or "password"
)
POSTGRES_HOST = os.environ.get("POSTGRES_HOST") or "127.0.0.1"
POSTGRES_PORT = os.environ.get("POSTGRES_PORT") or "5432"
POSTGRES_DB = os.environ.get("POSTGRES_DB") or "postgres"
AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME") or "us-east-2"

POSTGRES_API_SERVER_POOL_SIZE = int(
    os.environ.get("POSTGRES_API_SERVER_POOL_SIZE") or 40
)
POSTGRES_API_SERVER_POOL_OVERFLOW = int(
    os.environ.get("POSTGRES_API_SERVER_POOL_OVERFLOW") or 10
)

POSTGRES_API_SERVER_READ_ONLY_POOL_SIZE = int(
    os.environ.get("POSTGRES_API_SERVER_READ_ONLY_POOL_SIZE") or 10
)
POSTGRES_API_SERVER_READ_ONLY_POOL_OVERFLOW = int(
    os.environ.get("POSTGRES_API_SERVER_READ_ONLY_POOL_OVERFLOW") or 5
)

# defaults to False
# generally should only be used for
POSTGRES_USE_NULL_POOL = os.environ.get("POSTGRES_USE_NULL_POOL", "").lower() == "true"

# defaults to False
POSTGRES_POOL_PRE_PING = os.environ.get("POSTGRES_POOL_PRE_PING", "").lower() == "true"

# recycle timeout in seconds
POSTGRES_POOL_RECYCLE_DEFAULT = 60 * 20  # 20 minutes
try:
    POSTGRES_POOL_RECYCLE = int(
        os.environ.get("POSTGRES_POOL_RECYCLE", POSTGRES_POOL_RECYCLE_DEFAULT)
    )
except ValueError:
    POSTGRES_POOL_RECYCLE = POSTGRES_POOL_RECYCLE_DEFAULT

# RDS IAM authentication - enables IAM-based authentication for PostgreSQL
USE_IAM_AUTH = os.getenv("USE_IAM_AUTH", "False").lower() == "true"

# Redis IAM authentication - enables IAM-based authentication for Redis ElastiCache
# Note: This is separate from RDS IAM auth as they use different authentication mechanisms
USE_REDIS_IAM_AUTH = os.getenv("USE_REDIS_IAM_AUTH", "False").lower() == "true"
REDIS_SSL = os.getenv("REDIS_SSL", "").lower() == "true"
REDIS_HOST = os.environ.get("REDIS_HOST") or "localhost"
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or ""

# this assumes that other redis settings remain the same as the primary
REDIS_REPLICA_HOST = os.environ.get("REDIS_REPLICA_HOST") or REDIS_HOST

REDIS_AUTH_KEY_PREFIX = "fastapi_users_token:"

# Rate limiting for auth endpoints
RATE_LIMIT_WINDOW_SECONDS: int | None = None
_rate_limit_window_seconds_str = os.environ.get("RATE_LIMIT_WINDOW_SECONDS")
if _rate_limit_window_seconds_str is not None:
    try:
        RATE_LIMIT_WINDOW_SECONDS = int(_rate_limit_window_seconds_str)
    except ValueError:
        pass

RATE_LIMIT_MAX_REQUESTS: int | None = None
_rate_limit_max_requests_str = os.environ.get("RATE_LIMIT_MAX_REQUESTS")
if _rate_limit_max_requests_str is not None:
    try:
        RATE_LIMIT_MAX_REQUESTS = int(_rate_limit_max_requests_str)
    except ValueError:
        pass

AUTH_RATE_LIMITING_ENABLED = RATE_LIMIT_MAX_REQUESTS and RATE_LIMIT_WINDOW_SECONDS
# Used for general redis things
REDIS_DB_NUMBER = int(os.environ.get("REDIS_DB_NUMBER", 0))

# Used by celery as broker and backend
REDIS_DB_NUMBER_CELERY_RESULT_BACKEND = int(
    os.environ.get("REDIS_DB_NUMBER_CELERY_RESULT_BACKEND", 14)
)
REDIS_DB_NUMBER_CELERY = int(os.environ.get("REDIS_DB_NUMBER_CELERY", 15))  # broker

# will propagate to both our redis client as well as celery's redis client
REDIS_HEALTH_CHECK_INTERVAL = int(os.environ.get("REDIS_HEALTH_CHECK_INTERVAL", 60))

# our redis client only, not celery's
REDIS_POOL_MAX_CONNECTIONS = int(os.environ.get("REDIS_POOL_MAX_CONNECTIONS", 128))

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-settings
# should be one of "required", "optional", or "none"
REDIS_SSL_CERT_REQS = os.getenv("REDIS_SSL_CERT_REQS", "none")
REDIS_SSL_CA_CERTS = os.getenv("REDIS_SSL_CA_CERTS", None)

CELERY_RESULT_EXPIRES = int(os.environ.get("CELERY_RESULT_EXPIRES", 86400))  # seconds

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#broker-pool-limit
# Setting to None may help when there is a proxy in the way closing idle connections
CELERY_BROKER_POOL_LIMIT_DEFAULT = 10
try:
    CELERY_BROKER_POOL_LIMIT = int(
        os.environ.get("CELERY_BROKER_POOL_LIMIT", CELERY_BROKER_POOL_LIMIT_DEFAULT)
    )
except ValueError:
    CELERY_BROKER_POOL_LIMIT = CELERY_BROKER_POOL_LIMIT_DEFAULT

CELERY_WORKER_LIGHT_CONCURRENCY_DEFAULT = 24
try:
    CELERY_WORKER_LIGHT_CONCURRENCY = int(
        os.environ.get(
            "CELERY_WORKER_LIGHT_CONCURRENCY", CELERY_WORKER_LIGHT_CONCURRENCY_DEFAULT
        )
    )
except ValueError:
    CELERY_WORKER_LIGHT_CONCURRENCY = CELERY_WORKER_LIGHT_CONCURRENCY_DEFAULT

CELERY_WORKER_LIGHT_PREFETCH_MULTIPLIER_DEFAULT = 8
try:
    CELERY_WORKER_LIGHT_PREFETCH_MULTIPLIER = int(
        os.environ.get(
            "CELERY_WORKER_LIGHT_PREFETCH_MULTIPLIER",
            CELERY_WORKER_LIGHT_PREFETCH_MULTIPLIER_DEFAULT,
        )
    )
except ValueError:
    CELERY_WORKER_LIGHT_PREFETCH_MULTIPLIER = (
        CELERY_WORKER_LIGHT_PREFETCH_MULTIPLIER_DEFAULT
    )

CELERY_WORKER_DOCPROCESSING_CONCURRENCY_DEFAULT = 6
try:
    env_value = os.environ.get("CELERY_WORKER_DOCPROCESSING_CONCURRENCY")
    if not env_value:
        env_value = os.environ.get("NUM_INDEXING_WORKERS")

    if not env_value:
        env_value = str(CELERY_WORKER_DOCPROCESSING_CONCURRENCY_DEFAULT)
    CELERY_WORKER_DOCPROCESSING_CONCURRENCY = int(env_value)
except ValueError:
    CELERY_WORKER_DOCPROCESSING_CONCURRENCY = (
        CELERY_WORKER_DOCPROCESSING_CONCURRENCY_DEFAULT
    )

CELERY_WORKER_DOCFETCHING_CONCURRENCY_DEFAULT = 1
try:
    env_value = os.environ.get("CELERY_WORKER_DOCFETCHING_CONCURRENCY")
    if not env_value:
        env_value = os.environ.get("NUM_DOCFETCHING_WORKERS")

    if not env_value:
        env_value = str(CELERY_WORKER_DOCFETCHING_CONCURRENCY_DEFAULT)
    CELERY_WORKER_DOCFETCHING_CONCURRENCY = int(env_value)
except ValueError:
    CELERY_WORKER_DOCFETCHING_CONCURRENCY = (
        CELERY_WORKER_DOCFETCHING_CONCURRENCY_DEFAULT
    )

CELERY_WORKER_PRIMARY_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_PRIMARY_CONCURRENCY") or 4
)

CELERY_WORKER_PRIMARY_POOL_OVERFLOW = int(
    os.environ.get("CELERY_WORKER_PRIMARY_POOL_OVERFLOW") or 4
)

# Consolidated background worker (light, docprocessing, docfetching, heavy, kg_processing, monitoring, user_file_processing)
# separate workers' defaults: light=24, docprocessing=6, docfetching=1, heavy=4, kg=2, monitoring=1, user_file=2
# Total would be 40, but we use a more conservative default of 20 for the consolidated worker
CELERY_WORKER_BACKGROUND_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_BACKGROUND_CONCURRENCY") or 20
)

# Individual worker concurrency settings (used when USE_LIGHTWEIGHT_BACKGROUND_WORKER is False or on Kuberenetes deployments)
CELERY_WORKER_HEAVY_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_HEAVY_CONCURRENCY") or 4
)

CELERY_WORKER_KG_PROCESSING_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_KG_PROCESSING_CONCURRENCY") or 2
)

CELERY_WORKER_MONITORING_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_MONITORING_CONCURRENCY") or 1
)

CELERY_WORKER_USER_FILE_PROCESSING_CONCURRENCY = int(
    os.environ.get("CELERY_WORKER_USER_FILE_PROCESSING_CONCURRENCY") or 2
)

# The maximum number of tasks that can be queued up to sync to Vespa in a single pass
VESPA_SYNC_MAX_TASKS = 8192

DB_YIELD_PER_DEFAULT = 64

#####
# Connector Configs
#####
POLL_CONNECTOR_OFFSET = 30  # Minutes overlap between poll windows

# View the list here:
# https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/connectors/factory.py
# If this is empty, all connectors are enabled, this is an option for security heavy orgs where
# only very select connectors are enabled and admins cannot add other connector types
ENABLED_CONNECTOR_TYPES = os.environ.get("ENABLED_CONNECTOR_TYPES") or ""

# If set to true, curators can only access and edit assistants that they created
CURATORS_CANNOT_VIEW_OR_EDIT_NON_OWNED_ASSISTANTS = (
    os.environ.get("CURATORS_CANNOT_VIEW_OR_EDIT_NON_OWNED_ASSISTANTS", "").lower()
    == "true"
)

# Some calls to get information on expert users are quite costly especially with rate limiting
# Since experts are not used in the actual user experience, currently it is turned off
# for some connectors
ENABLE_EXPENSIVE_EXPERT_CALLS = False


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

NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP = (
    os.environ.get("NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP", "").lower()
    == "true"
)


#####
# Confluence Connector Configs
#####

CONFLUENCE_CONNECTOR_LABELS_TO_SKIP = [
    ignored_tag
    for ignored_tag in os.environ.get("CONFLUENCE_CONNECTOR_LABELS_TO_SKIP", "").split(
        ","
    )
    if ignored_tag
]

# Avoid to get archived pages
CONFLUENCE_CONNECTOR_INDEX_ARCHIVED_PAGES = (
    os.environ.get("CONFLUENCE_CONNECTOR_INDEX_ARCHIVED_PAGES", "").lower() == "true"
)

# Attachments exceeding this size will not be retrieved (in bytes)
CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD = int(
    os.environ.get("CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD", 10 * 1024 * 1024)
)
# Attachments with more chars than this will not be indexed. This is to prevent extremely
# large files from freezing indexing. 200,000 is ~100 google doc pages.
CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD = int(
    os.environ.get("CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD", 200_000)
)

# A JSON-formatted array. Each item in the array should have the following structure:
# {
#     "user_id": "1234567890",
#     "username": "bob",
#     "display_name": "Bob Fitzgerald",
#     "email": "bob@example.com",
#     "type": "known"
# }
_RAW_CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE = os.environ.get(
    "CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE", ""
)
CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE = cast(
    list[dict[str, str]] | None,
    (
        json.loads(_RAW_CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE)
        if _RAW_CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE
        else None
    ),
)

# Due to breakages in the confluence API, the timezone offset must be specified client side
# to match the user's specified timezone.

# The current state of affairs:
# CQL queries are parsed in the user's timezone and cannot be specified in UTC
# no API retrieves the user's timezone
# All data is returned in UTC, so we can't derive the user's timezone from that

# https://community.developer.atlassian.com/t/confluence-cloud-time-zone-get-via-rest-api/35954/16
# https://jira.atlassian.com/browse/CONFCLOUD-69670


def get_current_tz_offset() -> int:
    # datetime now() gets local time, datetime.now(timezone.utc) gets UTC time.
    # remove tzinfo to compare non-timezone-aware objects.
    time_diff = datetime.now() - datetime.now(timezone.utc).replace(tzinfo=None)
    return round(time_diff.total_seconds() / 3600)


# enter as a floating point offset from UTC in hours (-24 < val < 24)
# this will be applied globally, so it probably makes sense to transition this to per
# connector as some point.
# For the default value, we assume that the user's local timezone is more likely to be
# correct (i.e. the configured user's timezone or the default server one) than UTC.
# https://developer.atlassian.com/cloud/confluence/cql-fields/#created
CONFLUENCE_TIMEZONE_OFFSET = float(
    os.environ.get("CONFLUENCE_TIMEZONE_OFFSET", get_current_tz_offset())
)

GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD = int(
    os.environ.get("GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD", 10 * 1024 * 1024)
)

# Default size threshold for SharePoint files (20MB)
SHAREPOINT_CONNECTOR_SIZE_THRESHOLD = int(
    os.environ.get("SHAREPOINT_CONNECTOR_SIZE_THRESHOLD", 20 * 1024 * 1024)
)

BLOB_STORAGE_SIZE_THRESHOLD = int(
    os.environ.get("BLOB_STORAGE_SIZE_THRESHOLD", 20 * 1024 * 1024)
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

# Typically set to http://localhost:3000 for OAuth connector development
CONNECTOR_LOCALHOST_OVERRIDE = os.getenv("CONNECTOR_LOCALHOST_OVERRIDE")

# Egnyte specific configs
EGNYTE_CLIENT_ID = os.getenv("EGNYTE_CLIENT_ID")
EGNYTE_CLIENT_SECRET = os.getenv("EGNYTE_CLIENT_SECRET")

# Linear specific configs
LINEAR_CLIENT_ID = os.getenv("LINEAR_CLIENT_ID")
LINEAR_CLIENT_SECRET = os.getenv("LINEAR_CLIENT_SECRET")

# Slack specific configs
SLACK_NUM_THREADS = int(os.getenv("SLACK_NUM_THREADS") or 8)
MAX_SLACK_QUERY_EXPANSIONS = int(os.environ.get("MAX_SLACK_QUERY_EXPANSIONS", "5"))

DASK_JOB_CLIENT_ENABLED = (
    os.environ.get("DASK_JOB_CLIENT_ENABLED", "").lower() == "true"
)
EXPERIMENTAL_CHECKPOINTING_ENABLED = (
    os.environ.get("EXPERIMENTAL_CHECKPOINTING_ENABLED", "").lower() == "true"
)

LEAVE_CONNECTOR_ACTIVE_ON_INITIALIZATION_FAILURE = (
    os.environ.get("LEAVE_CONNECTOR_ACTIVE_ON_INITIALIZATION_FAILURE", "").lower()
    == "true"
)

PRUNING_DISABLED = -1
DEFAULT_PRUNING_FREQ = 60 * 60 * 24  # Once a day

ALLOW_SIMULTANEOUS_PRUNING = (
    os.environ.get("ALLOW_SIMULTANEOUS_PRUNING", "").lower() == "true"
)

# This is the maximum rate at which documents are queried for a pruning job. 0 disables the limitation.
MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE = int(
    os.environ.get("MAX_PRUNING_DOCUMENT_RETRIEVAL_PER_MINUTE", 0)
)

# comma delimited list of zendesk article labels to skip indexing for
ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS = os.environ.get(
    "ZENDESK_CONNECTOR_SKIP_ARTICLE_LABELS", ""
).split(",")


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
# More accurate results at the expense of indexing speed and index size (stores additional 4 MINI_CHUNK vectors)
ENABLE_MULTIPASS_INDEXING = (
    os.environ.get("ENABLE_MULTIPASS_INDEXING", "").lower() == "true"
)
# Enable contextual retrieval
ENABLE_CONTEXTUAL_RAG = os.environ.get("ENABLE_CONTEXTUAL_RAG", "").lower() == "true"

DEFAULT_CONTEXTUAL_RAG_LLM_NAME = "gpt-4o-mini"
DEFAULT_CONTEXTUAL_RAG_LLM_PROVIDER = "DevEnvPresetOpenAI"
# Finer grained chunking for more detail retention
# Slightly larger since the sentence aware split is a max cutoff so most minichunks will be under MINI_CHUNK_SIZE
# tokens. But we need it to be at least as big as 1/4th chunk size to avoid having a tiny mini-chunk at the end
MINI_CHUNK_SIZE = 150

# This is the number of regular chunks per large chunk
LARGE_CHUNK_RATIO = 4

# Include the document level metadata in each chunk. If the metadata is too long, then it is thrown out
# We don't want the metadata to overwhelm the actual contents of the chunk
SKIP_METADATA_IN_CHUNK = os.environ.get("SKIP_METADATA_IN_CHUNK", "").lower() == "true"
# Timeout to wait for job's last update before killing it, in hours
CLEANUP_INDEXING_JOBS_TIMEOUT = int(
    os.environ.get("CLEANUP_INDEXING_JOBS_TIMEOUT") or 3
)

# The indexer will warn in the logs whenver a document exceeds this threshold (in bytes)
INDEXING_SIZE_WARNING_THRESHOLD = int(
    os.environ.get("INDEXING_SIZE_WARNING_THRESHOLD") or 100 * 1024 * 1024
)

# during indexing, will log verbose memory diff stats every x batches and at the end.
# 0 disables this behavior and is the default.
INDEXING_TRACER_INTERVAL = int(os.environ.get("INDEXING_TRACER_INTERVAL") or 0)

# Enable multi-threaded embedding model calls for parallel processing
# Note: only applies for API-based embedding models
INDEXING_EMBEDDING_MODEL_NUM_THREADS = int(
    os.environ.get("INDEXING_EMBEDDING_MODEL_NUM_THREADS") or 8
)

# During an indexing attempt, specifies the number of batches which are allowed to
# exception without aborting the attempt.
INDEXING_EXCEPTION_LIMIT = int(os.environ.get("INDEXING_EXCEPTION_LIMIT") or 0)

# Maximum number of user file connector credential pairs to index in a single batch
# Setting this number too high may overload the indexing process
USER_FILE_INDEXING_LIMIT = int(os.environ.get("USER_FILE_INDEXING_LIMIT") or 100)

# Maximum file size in a document to be indexed
MAX_DOCUMENT_CHARS = int(os.environ.get("MAX_DOCUMENT_CHARS") or 5_000_000)
MAX_FILE_SIZE_BYTES = int(
    os.environ.get("MAX_FILE_SIZE_BYTES") or 2 * 1024 * 1024 * 1024
)  # 2GB in bytes

# Use document summary for contextual rag
USE_DOCUMENT_SUMMARY = os.environ.get("USE_DOCUMENT_SUMMARY", "true").lower() == "true"
# Use chunk summary for contextual rag
USE_CHUNK_SUMMARY = os.environ.get("USE_CHUNK_SUMMARY", "true").lower() == "true"
# Average summary embeddings for contextual rag (not yet implemented)
AVERAGE_SUMMARY_EMBEDDINGS = (
    os.environ.get("AVERAGE_SUMMARY_EMBEDDINGS", "false").lower() == "true"
)

MAX_TOKENS_FOR_FULL_INCLUSION = 4096


#####
# Tool Configs
#####
OKTA_PROFILE_TOOL_ENABLED = (
    os.environ.get("OKTA_PROFILE_TOOL_ENABLED", "").lower() == "true"
)
# API token for SSWS auth to Okta Admin API. If set, Users API will be used to enrich profile.
OKTA_API_TOKEN = os.environ.get("OKTA_API_TOKEN") or ""


#####
# Miscellaneous
#####
JOB_TIMEOUT = 60 * 60 * 6  # 6 hours default
# used to allow the background indexing jobs to use a different embedding
# model server than the API server
CURRENT_PROCESS_IS_AN_INDEXING_JOB = (
    os.environ.get("CURRENT_PROCESS_IS_AN_INDEXING_JOB", "").lower() == "true"
)
# Sets LiteLLM to verbose logging
LOG_ALL_MODEL_INTERACTIONS = (
    os.environ.get("LOG_ALL_MODEL_INTERACTIONS", "").lower() == "true"
)
# Logs Onyx only model interactions like prompts, responses, messages etc.
LOG_ONYX_MODEL_INTERACTIONS = (
    os.environ.get("LOG_ONYX_MODEL_INTERACTIONS", "").lower() == "true"
)
LOG_INDIVIDUAL_MODEL_TOKENS = (
    os.environ.get("LOG_INDIVIDUAL_MODEL_TOKENS", "").lower() == "true"
)
# If set to `true` will enable additional logs about Vespa query performance
# (time spent on finding the right docs + time spent fetching summaries from disk)
LOG_VESPA_TIMING_INFORMATION = (
    os.environ.get("LOG_VESPA_TIMING_INFORMATION", "").lower() == "true"
)
LOG_ENDPOINT_LATENCY = os.environ.get("LOG_ENDPOINT_LATENCY", "").lower() == "true"
LOG_POSTGRES_LATENCY = os.environ.get("LOG_POSTGRES_LATENCY", "").lower() == "true"
LOG_POSTGRES_CONN_COUNTS = (
    os.environ.get("LOG_POSTGRES_CONN_COUNTS", "").lower() == "true"
)
# Anonymous usage telemetry
DISABLE_TELEMETRY = os.environ.get("DISABLE_TELEMETRY", "").lower() == "true"

#####
# Braintrust Configuration
#####
# Braintrust project name
BRAINTRUST_PROJECT = os.environ.get("BRAINTRUST_PROJECT", "Onyx")
# Braintrust API key - if provided, Braintrust tracing will be enabled
BRAINTRUST_API_KEY = os.environ.get("BRAINTRUST_API_KEY") or ""
# Maximum concurrency for Braintrust evaluations
BRAINTRUST_MAX_CONCURRENCY = int(os.environ.get("BRAINTRUST_MAX_CONCURRENCY") or 5)

#####
# Langfuse Configuration
#####
# Langfuse API credentials - if provided, Langfuse tracing will be enabled
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY") or ""
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY") or ""
# Langfuse host URL (defaults to cloud instance)
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"

TOKEN_BUDGET_GLOBALLY_ENABLED = (
    os.environ.get("TOKEN_BUDGET_GLOBALLY_ENABLED", "").lower() == "true"
)

# Defined custom query/answer conditions to validate the query and the LLM answer.
# Format: list of strings
CUSTOM_ANSWER_VALIDITY_CONDITIONS = json.loads(
    os.environ.get("CUSTOM_ANSWER_VALIDITY_CONDITIONS", "[]")
)

VESPA_REQUEST_TIMEOUT = int(os.environ.get("VESPA_REQUEST_TIMEOUT") or "15")

SYSTEM_RECURSION_LIMIT = int(os.environ.get("SYSTEM_RECURSION_LIMIT") or "1000")

PARSE_WITH_TRAFILATURA = os.environ.get("PARSE_WITH_TRAFILATURA", "").lower() == "true"

# allow for custom error messages for different errors returned by litellm
# for example, can specify: {"Violated content safety policy": "EVIL REQUEST!!!"}
# to make it so that if an LLM call returns an error containing "Violated content safety policy"
# the end user will see "EVIL REQUEST!!!" instead of the default error message.
_LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS = os.environ.get(
    "LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS", ""
)
LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS: dict[str, str] | None = None
try:
    LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS = cast(
        dict[str, str], json.loads(_LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS)
    )
except json.JSONDecodeError:
    pass

# LLM Model Update API endpoint
LLM_MODEL_UPDATE_API_URL = os.environ.get("LLM_MODEL_UPDATE_API_URL")

# Federated Search Configs
MAX_FEDERATED_SECTIONS = int(
    os.environ.get("MAX_FEDERATED_SECTIONS", "5")
)  # max no. of federated sections to always keep
MAX_FEDERATED_CHUNKS = int(
    os.environ.get("MAX_FEDERATED_CHUNKS", "5")
)  # max no. of chunks to retrieve per federated connector

#####
# Enterprise Edition Configs
#####
# NOTE: this should only be enabled if you have purchased an enterprise license.
# if you're interested in an enterprise license, please reach out to us at
# founders@onyx.app OR message Chris Weaver or Yuhong Sun in the Onyx
# Discord community https://discord.gg/4NA5SbzrWb
ENTERPRISE_EDITION_ENABLED = (
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() == "true"
)

# Azure DALL-E Configurations
AZURE_DALLE_API_VERSION = os.environ.get("AZURE_DALLE_API_VERSION")
AZURE_DALLE_API_KEY = os.environ.get("AZURE_DALLE_API_KEY")
AZURE_DALLE_API_BASE = os.environ.get("AZURE_DALLE_API_BASE")
AZURE_DALLE_DEPLOYMENT_NAME = os.environ.get("AZURE_DALLE_DEPLOYMENT_NAME")

# configurable image model
IMAGE_MODEL_NAME = os.environ.get("IMAGE_MODEL_NAME", "gpt-image-1")

# Use managed Vespa (Vespa Cloud). If set, must also set VESPA_CLOUD_URL, VESPA_CLOUD_CERT_PATH and VESPA_CLOUD_KEY_PATH
MANAGED_VESPA = os.environ.get("MANAGED_VESPA", "").lower() == "true"

ENABLE_EMAIL_INVITES = os.environ.get("ENABLE_EMAIL_INVITES", "").lower() == "true"

# Security and authentication
DATA_PLANE_SECRET = os.environ.get(
    "DATA_PLANE_SECRET", ""
)  # Used for secure communication between the control and data plane
EXPECTED_API_KEY = os.environ.get(
    "EXPECTED_API_KEY", ""
)  # Additional security check for the control plane API

# API configuration
CONTROL_PLANE_API_BASE_URL = os.environ.get(
    "CONTROL_PLANE_API_BASE_URL", "http://localhost:8082"
)

OAUTH_SLACK_CLIENT_ID = os.environ.get("OAUTH_SLACK_CLIENT_ID", "")
OAUTH_SLACK_CLIENT_SECRET = os.environ.get("OAUTH_SLACK_CLIENT_SECRET", "")
OAUTH_CONFLUENCE_CLOUD_CLIENT_ID = os.environ.get(
    "OAUTH_CONFLUENCE_CLOUD_CLIENT_ID", ""
)
OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET = os.environ.get(
    "OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET", ""
)
OAUTH_JIRA_CLOUD_CLIENT_ID = os.environ.get("OAUTH_JIRA_CLOUD_CLIENT_ID", "")
OAUTH_JIRA_CLOUD_CLIENT_SECRET = os.environ.get("OAUTH_JIRA_CLOUD_CLIENT_SECRET", "")
OAUTH_GOOGLE_DRIVE_CLIENT_ID = os.environ.get("OAUTH_GOOGLE_DRIVE_CLIENT_ID", "")
OAUTH_GOOGLE_DRIVE_CLIENT_SECRET = os.environ.get(
    "OAUTH_GOOGLE_DRIVE_CLIENT_SECRET", ""
)

# JWT configuration
JWT_ALGORITHM = "HS256"

#####
# API Key Configs
#####
# refers to the rounds described here: https://passlib.readthedocs.io/en/stable/lib/passlib.hash.sha256_crypt.html
_API_KEY_HASH_ROUNDS_RAW = os.environ.get("API_KEY_HASH_ROUNDS")
API_KEY_HASH_ROUNDS = (
    int(_API_KEY_HASH_ROUNDS_RAW) if _API_KEY_HASH_ROUNDS_RAW else None
)


POD_NAME = os.environ.get("POD_NAME")
POD_NAMESPACE = os.environ.get("POD_NAMESPACE")


DEV_MODE = os.environ.get("DEV_MODE", "").lower() == "true"

INTEGRATION_TESTS_MODE = os.environ.get("INTEGRATION_TESTS_MODE", "").lower() == "true"

MOCK_CONNECTOR_FILE_PATH = os.environ.get("MOCK_CONNECTOR_FILE_PATH")

TEST_ENV = os.environ.get("TEST_ENV", "").lower() == "true"

# Set to true to mock LLM responses for testing purposes
MOCK_LLM_RESPONSE = (
    os.environ.get("MOCK_LLM_RESPONSE") if os.environ.get("MOCK_LLM_RESPONSE") else None
)


DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB = 20

# Number of pre-provisioned tenants to maintain
TARGET_AVAILABLE_TENANTS = int(os.environ.get("TARGET_AVAILABLE_TENANTS", "5"))


# Image summarization configuration
IMAGE_SUMMARIZATION_SYSTEM_PROMPT = os.environ.get(
    "IMAGE_SUMMARIZATION_SYSTEM_PROMPT",
    DEFAULT_IMAGE_SUMMARIZATION_SYSTEM_PROMPT,
)

# The user prompt for image summarization - the image filename will be automatically prepended
IMAGE_SUMMARIZATION_USER_PROMPT = os.environ.get(
    "IMAGE_SUMMARIZATION_USER_PROMPT",
    DEFAULT_IMAGE_SUMMARIZATION_USER_PROMPT,
)

IMAGE_ANALYSIS_SYSTEM_PROMPT = os.environ.get(
    "IMAGE_ANALYSIS_SYSTEM_PROMPT",
    DEFAULT_IMAGE_ANALYSIS_SYSTEM_PROMPT,
)

DISABLE_AUTO_AUTH_REFRESH = (
    os.environ.get("DISABLE_AUTO_AUTH_REFRESH", "").lower() == "true"
)

# Knowledge Graph Read Only User Configuration
DB_READONLY_USER: str = os.environ.get("DB_READONLY_USER", "db_readonly_user")
DB_READONLY_PASSWORD: str = urllib.parse.quote_plus(
    os.environ.get("DB_READONLY_PASSWORD") or "password"
)

# File Store Configuration
S3_FILE_STORE_BUCKET_NAME = (
    os.environ.get("S3_FILE_STORE_BUCKET_NAME") or "onyx-file-store-bucket"
)
S3_FILE_STORE_PREFIX = os.environ.get("S3_FILE_STORE_PREFIX") or "onyx-files"
# S3_ENDPOINT_URL is for MinIO and other S3-compatible storage. Leave blank for AWS S3.
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")
S3_VERIFY_SSL = os.environ.get("S3_VERIFY_SSL", "").lower() == "true"

# S3/MinIO Access Keys
S3_AWS_ACCESS_KEY_ID = os.environ.get("S3_AWS_ACCESS_KEY_ID")
S3_AWS_SECRET_ACCESS_KEY = os.environ.get("S3_AWS_SECRET_ACCESS_KEY")

# Should we force S3 local checksumming
S3_GENERATE_LOCAL_CHECKSUM = (
    os.environ.get("S3_GENERATE_LOCAL_CHECKSUM", "").lower() == "true"
)

# Forcing Vespa Language
# English: en, German:de, etc. See: https://docs.vespa.ai/en/linguistics.html
VESPA_LANGUAGE_OVERRIDE = os.environ.get("VESPA_LANGUAGE_OVERRIDE")
