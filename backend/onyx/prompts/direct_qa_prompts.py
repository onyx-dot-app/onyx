# The following prompts are used for the initial response before a chat history exists
# It is used also for the one shot direct QA flow
import json

from onyx.prompts.constants import DEFAULT_IGNORE_STATEMENT
from onyx.prompts.constants import FINAL_QUERY_PAT
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.prompts.constants import QUESTION_PAT
from onyx.prompts.constants import THOUGHT_PAT


ONE_SHOT_SYSTEM_PROMPT = """
You are a question answering system that is constantly learning and improving.
You can process and comprehend vast amounts of text and utilize this knowledge to provide \
accurate and detailed answers to diverse queries.
""".strip()

ONE_SHOT_TASK_PROMPT = """
Answer the final query below taking into account the context above where relevant. \
Ignore any provided context that is not relevant to the query.
""".strip()


WEAK_MODEL_SYSTEM_PROMPT = """
Respond to the user query using the following reference document.
""".lstrip()

WEAK_MODEL_TASK_PROMPT = """
Answer the user query below based on the reference document above.
"""


REQUIRE_JSON = """
You ALWAYS responds with ONLY a JSON containing an answer and quotes that support the answer.
""".strip()


JSON_HELPFUL_HINT = """
Hint: Make the answer as DETAILED as possible and respond in JSON format! \
Quotes MUST be EXACT substrings from provided documents!
""".strip()

CONTEXT_BLOCK = f"""
REFERENCE DOCUMENTS:
{GENERAL_SEP_PAT}
{{context_docs_str}}
{GENERAL_SEP_PAT}
"""

HISTORY_BLOCK = f"""
CONVERSATION HISTORY:
{GENERAL_SEP_PAT}
{{history_str}}
{GENERAL_SEP_PAT}
"""

COMPANY_NAME_BLOCK = """
The user works at {company_name}.
"""

COMPANY_DESCRIPTION_BLOCK = """Organization description: {company_description}
"""

# This has to be doubly escaped due to json containing { } which are also used for format strings
EMPTY_SAMPLE_JSON = {
    "answer": "Place your final answer here. It should be as DETAILED and INFORMATIVE as possible.",
    "quotes": [
        "each quote must be UNEDITED and EXACTLY as shown in the context documents!",
        "HINT, quotes are not shown to the user!",
    ],
}


# Default json prompt which can reference multiple docs and provide answer + quotes
# system_like_header is similar to system message, can be user provided or defaults to QA_HEADER
# context/history blocks are for context documents and conversation history, they can be blank
# task prompt is the task message of the prompt, can be blank, there is no default
JSON_PROMPT = f"""
{{system_prompt}}
{REQUIRE_JSON}
{{context_block}}{{history_block}}
{{task_prompt}}

SAMPLE RESPONSE:
```
{{{json.dumps(EMPTY_SAMPLE_JSON)}}}
```

{FINAL_QUERY_PAT.upper()}
{{user_query}}

{JSON_HELPFUL_HINT}
{{language_hint_or_none}}
""".strip()


# similar to the chat flow, but with the option of including a
# "conversation history" block
CITATIONS_PROMPT = f"""
Refer to the following {{context_type}} when responding to me.{DEFAULT_IGNORE_STATEMENT}

CONTEXT:
{GENERAL_SEP_PAT}
{{context_docs_str}}
{GENERAL_SEP_PAT}

{{history_block}}{{task_prompt}}

{QUESTION_PAT.upper()}
{{user_query}}
"""

# with tool calling, the documents are in a separate "tool" message
# NOTE: need to add the extra line about "getting right to the point" since the
# tool calling models from OpenAI tend to be more verbose
CITATIONS_PROMPT_FOR_TOOL_CALLING = f"""
Refer to the provided {{context_type}} when responding to me.{DEFAULT_IGNORE_STATEMENT} \
You should always get right to the point, and never use extraneous language.

{{history_block}}{{task_prompt}}

{QUESTION_PAT.upper()}
{{user_query}}
"""


# CURRENTLY DISABLED, CANNOT USE THIS ONE
# Default chain-of-thought style json prompt which uses multiple docs
# This one has a section for the LLM to output some non-answer "thoughts"
# COT (chain-of-thought) flow basically
COT_PROMPT = f"""
{ONE_SHOT_SYSTEM_PROMPT}

CONTEXT:
{GENERAL_SEP_PAT}
{{context_docs_str}}
{GENERAL_SEP_PAT}

You MUST respond in the following format:
```
{THOUGHT_PAT} Use this section as a scratchpad to reason through the answer.

{{{json.dumps(EMPTY_SAMPLE_JSON)}}}
```

{QUESTION_PAT.upper()} {{user_query}}
{JSON_HELPFUL_HINT}
{{language_hint_or_none}}
""".strip()


# User the following for easy viewing of prompts
if __name__ == "__main__":
    print(JSON_PROMPT)  # Default prompt used in the Onyx UI flow
