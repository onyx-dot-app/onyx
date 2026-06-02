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
