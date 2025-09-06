# Action IDs for Teams message actions
LIKE_BLOCK_ACTION_ID = "like_block_action"
DISLIKE_BLOCK_ACTION_ID = "dislike_block_action"
FOLLOWUP_BUTTON_ACTION_ID = "followup_button_action"
FOLLOWUP_BUTTON_RESOLVED_ACTION_ID = "followup_button_resolved_action"
GENERATE_ANSWER_BUTTON_ACTION_ID = "generate_answer_button_action"
IMMEDIATE_RESOLVED_BUTTON_ACTION_ID = "immediate_resolved_button_action"
KEEP_TO_YOURSELF_ACTION_ID = "keep_to_yourself_action"
SHOW_EVERYONE_ACTION_ID = "show_everyone_action"
VIEW_DOC_FEEDBACK_ID = "view_doc_feedback"
FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID = "feedback_doc_button_block_action"

# Teams-specific constants
TEAMS_BOT_USER_ID_PREFIX = "teams_bot_"
TEAMS_BOT_PERSONA_PREFIX = "teams_bot_persona_"

# Teams message types
TEAMS_MESSAGE_TYPE = "message"
TEAMS_MENTION_TYPE = "mention"
TEAMS_REACTION_TYPE = "reaction"

# Teams feedback emojis
TEAMS_LIKE_EMOJI = "👍"
TEAMS_DISLIKE_EMOJI = "👎"
TEAMS_FOLLOWUP_EMOJI = "❓"

# Teams message formatting
TEAMS_MESSAGE_FORMAT = "markdown"
TEAMS_CODE_BLOCK_FORMAT = "```"
TEAMS_QUOTE_FORMAT = ">"
TEAMS_BOLD_FORMAT = "**"
TEAMS_ITALIC_FORMAT = "*"
TEAMS_LINK_FORMAT = "[{text}]({url})"

# Teams API endpoints
TEAMS_GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
TEAMS_GRAPH_API_BETA = "https://graph.microsoft.com/beta"
TEAMS_AUTH_ENDPOINT = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
TEAMS_SCOPE = "https://graph.microsoft.com/.default"

# Teams webhook endpoints
TEAMS_WEBHOOK_ENDPOINT = "/api/teams/webhook"
TEAMS_WEBHOOK_VALIDATION_ENDPOINT = "/api/teams/webhook/validation"

# Teams subscription settings
TEAMS_SUBSCRIPTION_EXPIRY_DAYS = 3
TEAMS_SUBSCRIPTION_RENEWAL_BUFFER_HOURS = 24 