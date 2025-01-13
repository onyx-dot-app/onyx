from onyx.prompts.constants import GENERAL_SEP_PAT

DONT_USE_TOOL = "Don't use tool"
USE_TOOL = "Use tool"


"""Prompts to determine if we should use a custom tool or not."""


SHOULD_USE_CUSTOM_TOOL_SYSTEM_PROMPT = (
    "You are a large language model whose only job is to determine if the system should call an "
    "external tool to be able to answer the user's last message."
).strip()

SHOULD_USE_CUSTOM_TOOL_USER_PROMPT = f"""
Given the conversation history and a follow up query, determine if the system should use the \
'{{tool_name}}' tool to answer the user's query. The '{{tool_name}}' tool is a tool defined as: '{{tool_description}}'.

Respond with "{USE_TOOL}" if you think the tool would be helpful in respnding to the users query.
Respond with "{DONT_USE_TOOL}" otherwise.

Conversation History:
{GENERAL_SEP_PAT}
{{history}}
{GENERAL_SEP_PAT}

If you are at all unsure, respond with {DONT_USE_TOOL}.
Respond with EXACTLY and ONLY "{DONT_USE_TOOL}" or "{USE_TOOL}"

Follow up input:
{{query}}
""".strip()


"""Prompts to figure out the arguments to pass to a custom tool."""


TOOL_ARG_SYSTEM_PROMPT = (
    "You are a large language model whose only job is to determine the arguments to pass to an "
    "external tool."
).strip()


TOOL_ARG_USER_PROMPT = f"""
Given the following conversation and a follow up input, generate a \
dictionary of arguments to pass to the '{{tool_name}}' tool. \
The '{{tool_name}}' tool is a tool defined as: '{{tool_description}}'. \
The expected arguments are: {{tool_args}}.

Conversation:
{{history}}

Follow up input:
{{query}}

Respond with ONLY and EXACTLY a JSON object specifying the values of the arguments to pass to the tool.
""".strip()  # noqa: F541
