from enum import Enum

LIKE_BLOCK_ACTION_ID = "feedback-like"
DISLIKE_BLOCK_ACTION_ID = "feedback-dislike"
FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID = "feedback-doc-button"
IMMEDIATE_RESOLVED_BUTTON_ACTION_ID = "immediate-resolved-button"
FOLLOWUP_BUTTON_ACTION_ID = "followup-button"
FOLLOWUP_BUTTON_RESOLVED_ACTION_ID = "followup-resolved-button"
VIEW_DOC_FEEDBACK_ID = "view-doc-feedback"
GENERATE_ANSWER_BUTTON_ACTION_ID = "generate-answer-button"


class FeedbackVisibility(str, Enum):
    PRIVATE = "private"
    ANONYMOUS = "anonymous"
    PUBLIC = "public"
