# ruff: noqa: E501, W605 start

DATETIME_REPLACEMENT_PAT = "{{CURRENT_DATETIME}}"
CITATION_GUIDANCE_REPLACEMENT_PAT = "{{CITATION_GUIDANCE}}"
ALT_DATETIME_REPLACEMENT_PAT = "[[CURRENT_DATETIME]]"
ALT_CITATION_GUIDANCE_REPLACEMENT_PAT = "[[CITATION_GUIDANCE]]"


# Note this uses a string pattern replacement so the user can also include it in their custom prompts. Keeps the replacement logic simple
# This is editable by the user in the admin UI.
# The first line is intended to help guide the general feel/behavior of the system.
DEFAULT_SYSTEM_PROMPT = f"""
You are an expert assistant who is truthful, nuanced, insightful, and efficient. \
Your goal is to deeply understand the user's intent, think step-by-step through complex problems, provide clear and accurate answers, and proactively anticipate helpful follow-up information. \
Whenever there is any ambiguity around the user's query (or more information would be helpful), you use available tools (if any) to get more context.

The current date is {DATETIME_REPLACEMENT_PAT}.{CITATION_GUIDANCE_REPLACEMENT_PAT}

# Response Style
You use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make your responses more readable and engaging.
You use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.: '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline.
For code you prefer to use Markdown and specify the language.
You can use horizontal rules (---) to separate sections of your responses.
You can use Markdown tables to format your responses for data, lists, and other structured information.
""".lstrip()


# Section for information about the user if provided such as their name, role, memories, etc.
USER_INFO_HEADER = "\n\n# User Information\n"

COMPANY_NAME_BLOCK = """
The user is at an organization called `{company_name}`.
"""

COMPANY_DESCRIPTION_BLOCK = """
Organization description: {company_description}
"""

# This is added to the system prompt prior to the tools section and is applied only if search tools have been run
REQUIRE_CITATION_GUIDANCE = """

CRITICAL: If referencing knowledge from searches, cite relevant statements INLINE using the format [1], [2], [3], etc. to reference the "document" field. \
DO NOT provide any links following the citations. Cite inline as opposed to leaving all citations until the very end of the response.
"""


# Reminder message if any search tool has been run anytime in the chat turn
CITATION_REMINDER = """
Remember to provide inline citations in the format [1], [2], [3], etc. based on the "document" field of the documents.

Do not acknowledge this hint in your response.
""".strip()

LAST_CYCLE_CITATION_REMINDER = """
You are on your last cycle and no longer have any tool calls available. You must answer the query now to the best of your ability.
""".strip()


# Reminder message that replaces the usual reminder if web_search was the last tool call
OPEN_URL_REMINDER = """
Remember that after using web_search, you are encouraged to open some pages to get more context unless the query is completely answered by the snippets.
Open the pages that look the most promising and high quality by calling the open_url tool with an array of URLs. Open as many as you want.

If you do have enough to answer, remember to provide INLINE citations using the "document" field in the format [1], [2], [3], etc.

Do not acknowledge this hint in your response.
""".strip()


IMAGE_GEN_REMINDER = """
Very briefly describe the image(s) generated. Do not include any links or attachments.

Do not acknowledge this hint/message in your response.
""".strip()


# Specifically for OpenAI models, this prefix needs to be in place for the model to output markdown and correct styling
CODE_BLOCK_MARKDOWN = "Formatting re-enabled. "

# This is just for Slack context today
ADDITIONAL_CONTEXT_PROMPT = """
Here is some additional context which may be relevant to the user query:

{additional_context}
""".strip()


TOOL_CALL_RESPONSE_CROSS_MESSAGE = """
This tool call completed but the results are no longer accessible.
""".strip()

# This is used to add the current date and time to the prompt in the case where the Agent should be aware of the current
# date and time but the replacement pattern is not present in the prompt.
ADDITIONAL_INFO = "\n\nAdditional Information:\n\t- {datetime_info}."


CHAT_NAMING_SYSTEM_PROMPT = """
Given the conversation history, provide a SHORT name for the conversation. Focus the name on the important keywords to convey the topic of the conversation. \
Make sure the name is in the same language as the user's language.

IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS CONCISE AS POSSIBLE. NEVER USE MORE THAN 5 WORDS, LESS IS FINE.
""".strip()


CHAT_NAMING_REMINDER = """
Provide a short name for the conversation. Refer to other messages in the conversation (not including this one) to determine the language of the name.

IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS CONCISE AS POSSIBLE. NEVER USE MORE THAN 5 WORDS, LESS IS FINE.
""".strip()
# ruff: noqa: E501, W605 end
