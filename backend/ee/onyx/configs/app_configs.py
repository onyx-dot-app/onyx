import json
import os


#####
# Auto Permission Sync
#####
# should generally only be used for sources that support polling of permissions
# e.g. can pull in only permission changes rather than having to go through all
# documents every time
DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY") or 5 * 60
)


#####
# Confluence
#####

# In seconds, default is 30 minutes
CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY = int(
    os.environ.get("CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY") or 30 * 60
)
# In seconds, default is 30 minutes
CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY") or 30 * 60
)
# This is a boolean that determines if anonymous access is public
# Default behavior is to not make the page public and instead add a group
# that contains all the users that we found in Confluence
CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC = (
    os.environ.get("CONFLUENCE_ANONYMOUS_ACCESS_IS_PUBLIC", "").lower() == "true"
)


#####
# JIRA
#####

# In seconds, default is 30 minutes
JIRA_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("JIRA_PERMISSION_DOC_SYNC_FREQUENCY") or 30 * 60
)


#####
# Google Drive
#####
GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY = int(
    os.environ.get("GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY") or 5 * 60
)


#####
# GitHub
#####
# In seconds, default is 5 minutes
GITHUB_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("GITHUB_PERMISSION_DOC_SYNC_FREQUENCY") or 5 * 60
)
# In seconds, default is 5 minutes
GITHUB_PERMISSION_GROUP_SYNC_FREQUENCY = int(
    os.environ.get("GITHUB_PERMISSION_GROUP_SYNC_FREQUENCY") or 5 * 60
)


#####
# Slack
#####
SLACK_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("SLACK_PERMISSION_DOC_SYNC_FREQUENCY") or 5 * 60
)

NUM_PERMISSION_WORKERS = int(os.environ.get("NUM_PERMISSION_WORKERS") or 2)


#####
# Teams
#####
# In seconds, default is 5 minutes
TEAMS_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("TEAMS_PERMISSION_DOC_SYNC_FREQUENCY") or 5 * 60
)

#####
# SharePoint
#####
# In seconds, default is 30 minutes
SHAREPOINT_PERMISSION_DOC_SYNC_FREQUENCY = int(
    os.environ.get("SHAREPOINT_PERMISSION_DOC_SYNC_FREQUENCY") or 30 * 60
)

# In seconds, default is 5 minutes
SHAREPOINT_PERMISSION_GROUP_SYNC_FREQUENCY = int(
    os.environ.get("SHAREPOINT_PERMISSION_GROUP_SYNC_FREQUENCY") or 5 * 60
)


####
# Celery Job Frequency
####
CHECK_TTL_MANAGEMENT_TASK_FREQUENCY_IN_HOURS = float(
    os.environ.get("CHECK_TTL_MANAGEMENT_TASK_FREQUENCY_IN_HOURS") or 1
)  # float for easier testing


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

# The posthog client does not accept empty API keys or hosts however it fails silently
# when the capture is called. These defaults prevent Posthog issues from breaking the Onyx app
POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY") or "FooBar"
POSTHOG_HOST = os.environ.get("POSTHOG_HOST") or "https://us.i.posthog.com"

HUBSPOT_TRACKING_URL = os.environ.get("HUBSPOT_TRACKING_URL")

GATED_TENANTS_KEY = "gated_tenants"
