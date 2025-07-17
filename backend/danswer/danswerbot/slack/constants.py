from enum import Enum

LIKE_BLOCK_ACTION_ID = "feedback-like"
DISLIKE_BLOCK_ACTION_ID = "feedback-dislike"
FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID = "feedback-doc-button"
IMMEDIATE_RESOLVED_BUTTON_ACTION_ID = "immediate-resolved-button"
FOLLOWUP_BUTTON_ACTION_ID = "followup-button"
FOLLOWUP_BUTTON_RESOLVED_ACTION_ID = "followup-resolved-button"
SLACK_CHANNEL_ID = "channel_id"
VIEW_DOC_FEEDBACK_ID = "view-doc-feedback"


class FeedbackVisibility(str, Enum):
    PRIVATE = "private"
    ANONYMOUS = "anonymous"
    PUBLIC = "public"


# Constants for curated response handling
CURATED_RESPONSE_CONFIG_KEY = "curated_response_config"
ENABLE_CURATED_RESPONSE_KEY = "enable_curated_response_integration"
RESPONSE_MESSAGE_KEY = "response_message"
USER_TITLE_FILTER_KEY = "curated_response_user_title_filter"
USER_KEY = "user"
USER_ID_KEY = "id"
USER_PROFILE_KEY = "profile"
USER_TITLE_KEY = "title"
