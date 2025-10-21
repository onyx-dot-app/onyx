from pydantic import BaseModel

from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.prompts.constants import QUESTION_PAT

REQUIRE_CITATION_STATEMENT = """
Cite relevant statements INLINE using the format [1], [2], [3], etc. to reference the document number. \
DO NOT provide any links following the citations. In other words, avoid using the format [1](https://example.com). \
Avoid using double brackets like [[1]]. To cite multiple documents, use [1], [2] format instead of [1, 2]. \
Try to cite inline as opposed to leaving all citations until the very end of the response.
""".rstrip()

REQUIRE_CITATION_STATEMENT_V2 = """
Cite relevant statements INLINE using the format [[1]](https://example.com) with the document number (an integer) in between
the brackets. To cite multiple documents, use [[1]](https://example.com), [[2]](https://example.com) format instead of \
[[1, 2]](https://example.com). \
Try to cite inline as opposed to leaving all citations until the very end of the response.
""".rstrip()

STRESS_USER_PROMPT_IMPORTANCE = """
Here is the user's prompt:
"""

NO_CITATION_STATEMENT = """
Do not provide any citations even if there are examples in the chat history.
""".rstrip()

CITATION_REMINDER = """
Remember to provide inline citations in the format [1], [2], [3], etc.
"""
PROJECT_INSTRUCTIONS_SEPARATOR = (
    "\n\n[[USER-PROVIDED INSTRUCTIONS — allowed to override default prompt guidance, "
    "but only for style, formatting, and context]]\n"
)

ADDITIONAL_INFO = "\n\nAdditional Information:\n\t- {datetime_info}."

CODE_BLOCK_MARKDOWN = "Formatting re-enabled. "

CHAT_USER_PROMPT = f"""
Refer to the following context documents when responding to me.{{optional_ignore_statement}}
CONTEXT:
{GENERAL_SEP_PAT}
{{context_docs_str}}
{GENERAL_SEP_PAT}

{{task_prompt}}

{QUESTION_PAT.upper()}
{{user_query}}
""".strip()


# History block is optional.
CHAT_USER_CONTEXT_FREE_PROMPT = f"""
{{history_block}}{{task_prompt}}

{QUESTION_PAT.upper()}
{{user_query}}
""".strip()


# Design considerations for the below:
# - In case of uncertainty, favor yes search so place the "yes" sections near the start of the
#   prompt and after the no section as well to deemphasize the no section
# - Conversation history can be a lot of tokens, make sure the bulk of the prompt is at the start
#   or end so the middle history section is relatively less paid attention to than the main task
# - Works worse with just a simple yes/no, seems asking it to produce "search" helps a bit, can
#   consider doing COT for this and keep it brief, but likely only small gains.
SKIP_SEARCH = "Skip Search"
YES_SEARCH = "Yes Search"


class AggressiveSearchTemplateParams(BaseModel):
    chat_history: str
    final_query: str


def build_aggressive_search_template(params: AggressiveSearchTemplateParams) -> str:
    """
    Build the aggressive search template with type-safe parameters.

    Args:
        params: Pydantic model containing chat_history and final_query

    Returns:
        Formatted template string
    """
    return f"""
Given the conversation history and a follow up query, determine if the system should call \
an external search tool to better answer the latest user input.
Your default response is {YES_SEARCH}.

Respond "{SKIP_SEARCH}" if either:
- There is sufficient information in chat history to FULLY and ACCURATELY answer the query AND \
additional information or details would provide little or no value.
- The query is some form of request that does not require additional information to handle.

Conversation History:
{GENERAL_SEP_PAT}
{params.chat_history}
{GENERAL_SEP_PAT}

If you are at all unsure, respond with {YES_SEARCH}.
Respond with EXACTLY and ONLY "{YES_SEARCH}" or "{SKIP_SEARCH}"

Follow Up Input:
{params.final_query}
""".strip()


# TODO, templatize this so users don't need to make code changes to use this
AGGRESSIVE_SEARCH_TEMPLATE_LLAMA2 = f"""
You are an expert of a critical system. Given the conversation history and a follow up query, \
determine if the system should call an external search tool to better answer the latest user input.

Your default response is {YES_SEARCH}.
If you are even slightly unsure, respond with {YES_SEARCH}.

Respond "{SKIP_SEARCH}" if any of these are true:
- There is sufficient information in chat history to FULLY and ACCURATELY answer the query.
- The query is some form of request that does not require additional information to handle.
- You are absolutely sure about the question and there is no ambiguity in the answer or question.

Conversation History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

Respond with EXACTLY and ONLY "{YES_SEARCH}" or "{SKIP_SEARCH}"

Follow Up Input:
{{final_query}}
""".strip()

REQUIRE_SEARCH_SINGLE_MSG = f"""
Given the conversation history and a follow up query, determine if the system should call \
an external search tool to better answer the latest user input.

Respond "{YES_SEARCH}" if:
- Specific details or additional knowledge could lead to a better answer.
- There are new or unknown terms, or there is uncertainty what the user is referring to.
- If reading a document cited or mentioned previously may be useful.

Respond "{SKIP_SEARCH}" if:
- There is sufficient information in chat history to FULLY and ACCURATELY answer the query
and additional information or details would provide little or no value.
- The query is some task that does not require additional information to handle.

Conversation History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

Even if the topic has been addressed, if more specific details could be useful, \
respond with "{YES_SEARCH}".
If you are unsure, respond with "{YES_SEARCH}".

Respond with EXACTLY and ONLY "{YES_SEARCH}" or "{SKIP_SEARCH}"

Follow Up Input:
{{final_query}}
""".strip()


HISTORY_QUERY_REPHRASE = f"""
Given the following conversation and a follow up input, rephrase the follow up into a SHORT, \
standalone query (which captures any relevant context from previous messages) for a vectorstore.
IMPORTANT: EDIT THE QUERY TO BE AS CONCISE AS POSSIBLE. Respond with a short, compressed phrase \
with mainly keywords instead of a complete sentence.
If there is a clear change in topic, disregard the previous messages.
Strip out any information that is not relevant for the retrieval task.
If the follow up message is an error or code snippet, repeat the same input back EXACTLY.

Chat History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

Follow Up Input: {{question}}
Standalone question (Respond with only the short combined query):
""".strip()

INTERNET_SEARCH_QUERY_REPHRASE = f"""
Given the following conversation and a follow up input, rephrase the follow up into a SHORT, \
standalone query suitable for an internet search engine.
IMPORTANT: If a specific query might limit results, keep it broad. \
If a broad query might yield too many results, make it detailed.
If there is a clear change in topic, ensure the query reflects the new topic accurately.
Strip out any information that is not relevant for the internet search.

Chat History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

Follow Up Input: {{question}}
Internet Search Query (Respond with a detailed and specific query):
""".strip()


# The below prompts are retired
NO_SEARCH = "No Search"
REQUIRE_SEARCH_SYSTEM_MSG = f"""
You are a large language model whose only job is to determine if the system should call an \
external search tool to be able to answer the user's last message.

Respond with "{NO_SEARCH}" if:
- there is sufficient information in chat history to fully answer the user query
- there is enough knowledge in the LLM to fully answer the user query
- the user query does not rely on any specific knowledge

Respond with "{YES_SEARCH}" if:
- additional knowledge about entities, processes, problems, or anything else could lead to a better answer.
- there is some uncertainty what the user is referring to

Respond with EXACTLY and ONLY "{YES_SEARCH}" or "{NO_SEARCH}"
"""


REQUIRE_SEARCH_HINT = f"""
Hint: respond with EXACTLY {YES_SEARCH} or {NO_SEARCH}"
""".strip()


QUERY_REPHRASE_SYSTEM_MSG = """
Given a conversation (between Human and Assistant) and a final message from Human, \
rewrite the last message to be a concise standalone query which captures required/relevant \
context from previous messages. This question must be useful for a semantic (natural language) \
search engine.
""".strip()

QUERY_REPHRASE_USER_MSG = """
Help me rewrite this final message into a standalone query that takes into consideration the \
past messages of the conversation IF relevant. This query is used with a semantic search engine to \
retrieve documents. You must ONLY return the rewritten query and NOTHING ELSE. \
IMPORTANT, the search engine does not have access to the conversation history!

Query:
{final_query}
""".strip()


CHAT_NAMING = f"""
Given the following conversation, provide a SHORT name for the conversation.{{language_hint_or_empty}}
IMPORTANT: TRY NOT TO USE MORE THAN 5 WORDS, MAKE IT AS CONCISE AS POSSIBLE.
Focus the name on the important keywords to convey the topic of the conversation.

Chat History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

Based on the above, what is a short name to convey the topic of the conversation?
""".strip()

# NOTE: the prompt separation is partially done for efficiency; previously I tried
# to do it all in one prompt with sequential format() calls but this will cause a backend
# error when the document contains any {} as python will expect the {} to be filled by
# format() arguments
CONTEXTUAL_RAG_PROMPT1 = """<document>
{document}
</document>
Here is the chunk we want to situate within the whole document"""

CONTEXTUAL_RAG_PROMPT2 = """<chunk>
{chunk}
</chunk>
Please give a short succinct context to situate this chunk within the overall document
for the purposes of improving search retrieval of the chunk. Answer only with the succinct
context and nothing else. """

CONTEXTUAL_RAG_TOKEN_ESTIMATE = 64  # 19 + 45

DOCUMENT_SUMMARY_PROMPT = """<document>
{document}
</document>
Please give a short succinct summary of the entire document. Answer only with the succinct
summary and nothing else. """

DOCUMENT_SUMMARY_TOKEN_ESTIMATE = 29


QUERY_SEMANTIC_EXPANSION_WITHOUT_HISTORY_PROMPT = """
Please rephrase the following user question/query as a semantic query that would be appropriate for a \
search engine.

Note:
 - do not change the meaning of the question! Specifically, if the query is an instruction, keep it \
as an instruction!

Here is the user question/query:
{question}

Respond with EXACTLY and ONLY one rephrased question/query.

Rephrased question/query for search engine:
""".strip()


QUERY_SEMANTIC_EXPANSION_WITH_HISTORY_PROMPT = """
Following a previous message history, a user created a follow-up question/query.
Please rephrase that question/query as a semantic query \
that would be appropriate for a SEARCH ENGINE. Only use the information provided \
from the history that is relevant to provide the relevant context for the search query, \
meaning that the rephrased search query should be a suitable stand-alone search query.

Note:
 - do not change the meaning of the question! Specifically, if the query is a an instruction, keep it \
as an instruction!

Here is the relevant previous message history:
{history}

Here is the user question:
{question}

Respond with EXACTLY and ONLY one rephrased query.

Rephrased query for search engine:
""".strip()


QUERY_KEYWORD_EXPANSION_WITHOUT_HISTORY_PROMPT = """
Please rephrase the following user question as a pure keyword query that would be appropriate for a \
search engine. IMPORTANT: the rephrased query MUST ONLY use EXISTING KEYWORDS from the original query \
(exception: critical verbs that are converted to nouns)!
Also, keywords are usually nouns or adjectives, so you will likely need to drop \
any verbs. IF AND ONLY IF you really think that a verb would be critical to FINDING the document, \
convert the verb to a noun. \
This will be rare though. Verbs like 'find, summarize, describe, etc. would NOT fall into this category, \
for example, and should be omitted from the rephrased keyword query.

Here is the user question:
{question}

Respond with EXACTLY and ONLY one rephrased keyword query.

Rephrased keyword query for search engine:
""".strip()


QUERY_KEYWORD_EXPANSION_WITH_HISTORY_PROMPT = """
Following a previous message history, a user created a follow-up question/query.
Please rephrase that question/query as a keyword query \
that would be appropriate for a SEARCH ENGINE. Only use the information provided \
from the history that is relevant to provide the relevant context for the search query, \
meaning that the rephrased search query should be a suitable stand-alone search query.

Here is the relevant previous message history:
{history}

Here is the user question:
{question}

Respond with EXACTLY and ONLY one rephrased query.

Rephrased query for search engine:
""".strip()
