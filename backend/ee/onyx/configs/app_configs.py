import json
import os

# Applicable for OIDC Auth
OPENID_CONFIG_URL = os.environ.get("OPENID_CONFIG_URL", "")

# Applicable for SAML Auth
SAML_CONF_DIR = os.environ.get("SAML_CONF_DIR") or "/app/ee/onyx/configs/saml_config"


#####
# Auto Permission Sync
#####
# In seconds, default is 5 minutes
CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY = int(
    os.environ.get("CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY") or 5 * 60
)
# This is a boolean that determines if anonymous access is public
# Default behavior is to not make the page public and instead add a group
# that contains all the users that we found in Confluence
CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC = (
    os.environ.get("CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC", "").lower() == "true"
)
# In seconds, default is 5 minutes
CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY") or 5 * 60
)
NUM_PERMISSION_WORKERS = int(os.environ.get("NUM_PERMISSION_WORKERS") or 2)


STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE")

OPENAI_DEFAULT_API_KEY = os.environ.get("OPENAI_DEFAULT_API_KEY")
ANTHROPIC_DEFAULT_API_KEY = os.environ.get("ANTHROPIC_DEFAULT_API_KEY")
COHERE_DEFAULT_API_KEY = os.environ.get("COHERE_DEFAULT_API_KEY")

# JWT Public Key URL
JWT_PUBLIC_KEY_URL: str | None = os.getenv("JWT_PUBLIC_KEY_URL", None)


# Super Users
SUPER_USERS = json.loads(os.environ.get("SUPER_USERS", "[]"))
SUPER_CLOUD_API_KEY = os.environ.get("SUPER_CLOUD_API_KEY", "api_key")

OAUTH_SLACK_CLIENT_ID = os.environ.get("OAUTH_SLACK_CLIENT_ID", "")
OAUTH_SLACK_CLIENT_SECRET = os.environ.get("OAUTH_SLACK_CLIENT_SECRET", "")
OAUTH_CONFLUENCE_CLIENT_ID = os.environ.get("OAUTH_CONFLUENCE_CLIENT_ID", "")
OAUTH_CONFLUENCE_CLIENT_SECRET = os.environ.get("OAUTH_CONFLUENCE_CLIENT_SECRET", "")
OAUTH_JIRA_CLIENT_ID = os.environ.get("OAUTH_JIRA_CLIENT_ID", "")
OAUTH_JIRA_CLIENT_SECRET = os.environ.get("OAUTH_JIRA_CLIENT_SECRET", "")
OAUTH_GOOGLE_DRIVE_CLIENT_ID = os.environ.get("OAUTH_GOOGLE_DRIVE_CLIENT_ID", "")
OAUTH_GOOGLE_DRIVE_CLIENT_SECRET = os.environ.get(
    "OAUTH_GOOGLE_DRIVE_CLIENT_SECRET", ""
)


# The posthog client does not accept empty API keys or hosts however it fails silently
# when the capture is called. These defaults prevent Posthog issues from breaking the Onyx app
POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY") or "FooBar"
POSTHOG_HOST = os.environ.get("POSTHOG_HOST") or "https://us.i.posthog.com"

HUBSPOT_TRACKING_URL = os.environ.get("HUBSPOT_TRACKING_URL")

ANONYMOUS_USER_COOKIE_NAME = "onyx_anonymous_user"
