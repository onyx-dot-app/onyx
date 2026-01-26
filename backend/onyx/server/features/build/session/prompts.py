"""Prompts used for build session operations."""

# Build session naming prompts (similar to chat naming)
BUILD_NAMING_SYSTEM_PROMPT = """
Given the user's build request, provide a SHORT name for the build session. \
Focus on the main task or goal the user wants to accomplish.

IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS CONCISE AS POSSIBLE. \
NEVER USE MORE THAN 5 WORDS, LESS IS FINE.
""".strip()

BUILD_NAMING_USER_PROMPT = """
User's request: {user_message}

Provide a short name for this build session.
""".strip()


# Follow-up suggestion prompts
FOLLOWUP_SUGGESTIONS_SYSTEM_PROMPT = """You generate follow-up suggestions for an AI workplace assistant conversation.

Given the user's initial request and the assistant's response, generate exactly 2 suggestions:

1. ADD: A suggestion to extend or enhance what was built.
Start with "Great! Now add..." or similar positive acknowledgment + extension.

2. QUESTION: A follow-up question the user might want to ask about the implementation or to explore further.
Start with something like "Can you explain..." or "How does...".

IMPORTANT:
- Keep each suggestion SHORT (under 100 characters preferred, max 150)
- Make them specific to the actual request and response
- They should feel natural, like what a user might actually type
- Output ONLY a JSON array with objects containing "theme" and "text" fields
- Do NOT wrap in code fences or add any other text

Example output:
[{"theme": "add", "text": "Great! Now add form validation for the email field"},
{"theme": "question", "text": "Can you explain how the authentication flow works?"}]""".strip()

FOLLOWUP_SUGGESTIONS_USER_PROMPT = """User's request:
{user_message}

Assistant's response:
{assistant_message}

Generate 2 follow-up suggestions (add, question) as a JSON array:""".strip()
