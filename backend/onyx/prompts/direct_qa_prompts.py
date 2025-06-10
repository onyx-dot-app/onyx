# The following prompts are used for the initial response before a chat history exists
# It is used also for the one shot direct QA flow
import json

from onyx.prompts.constants import DEFAULT_IGNORE_STATEMENT
from onyx.prompts.constants import FINAL_QUERY_PAT
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.prompts.constants import QUESTION_PAT
from onyx.prompts.constants import THOUGHT_PAT


ONE_SHOT_SYSTEM_PROMPT = """
Ты - система ответов на вопросы, которая постоянно обучается и совершенствуется.
Ты можешь обрабатывать и понимать огромное количество текста и использовать эти знания для предоставления \
точных и подробных ответов на различные запросы.
""".strip()

ONE_SHOT_TASK_PROMPT = """
Ответь на последний запрос, приведенный ниже, с учетом приведенного выше контекста, если это уместно. \
Игнорируй любой предоставленный контекст, который не имеет отношения к запросу.
""".strip()


WEAK_MODEL_SYSTEM_PROMPT = """
Ответь на запрос пользователя, используя следующий справочный документ.
""".lstrip()

WEAK_MODEL_TASK_PROMPT = """
Ответь на приведенный ниже запрос пользователя, основываясь на приведенном выше справочном документе.
"""


REQUIRE_JSON = """
ВСЕГДА отвечай ТОЛЬКО JSON-файлом, содержащим ответ и кавычки, подтверждающие этот ответ.
""".strip()


JSON_HELPFUL_HINT = """
Подсказка: ответь как можно подробнее и в формате JSON! \
Кавычки ДОЛЖНЫ быть ТОЧНЫМИ подстроками из предоставленных документов!
""".strip()

CONTEXT_BLOCK = f"""
СПРАВОЧНЫЕ ДОКУМЕНТЫ:
{GENERAL_SEP_PAT}
{{context_docs_str}}
{GENERAL_SEP_PAT}
"""

HISTORY_BLOCK = f"""
ИСТОРИЯ ЧАТА:
{GENERAL_SEP_PAT}
{{history_str}}
{GENERAL_SEP_PAT}
"""


# This has to be doubly escaped due to json containing { } which are also used for format strings
EMPTY_SAMPLE_JSON = {
    "answer": "Размести свой окончательный ответ здесь. Он должен быть максимально ПОДРОБНЫМ и ИНФОРМАТИВНЫМ.",
    "quotes": [
        "каждая цитата должна быть НЕОТРЕДАКТИРОВАННОЙ и точно такой, как указано в контекстных документах!",
        "ПОДСКАЗКА, кавычки не показываются пользователю!",
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

ПРИМЕРНЫЙ ОТВЕТ:
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
Отвечая мне, используй следуюущие {{context_type}}.{DEFAULT_IGNORE_STATEMENT}

КОНТЕКСТ:
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
Отвечая мне, используй следующие {{context_type}}.{DEFAULT_IGNORE_STATEMENT} \
Ты всегда должнен переходить прямо к делу и никогда не использовать посторонних выражений.

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

КОНТЕКСТ:
{GENERAL_SEP_PAT}
{{context_docs_str}}
{GENERAL_SEP_PAT}

Отвечай в следующем формате:
```
{THOUGHT_PAT} Используй этот раздел как блокнот для размышлений над ответом.

{{{json.dumps(EMPTY_SAMPLE_JSON)}}}
```

{QUESTION_PAT.upper()} {{user_query}}
{JSON_HELPFUL_HINT}
{{language_hint_or_none}}
""".strip()


# User the following for easy viewing of prompts
if __name__ == "__main__":
    print(JSON_PROMPT)  # Default prompt used in the Onyx UI flow
