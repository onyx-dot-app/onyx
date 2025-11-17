# How it works and rationale:
# First - this works best emprically across multiple LLMs, some of this is back-explaining reasons based on results.
#
# The system prompt is kept simple and as similar to typical system prompts as possible to stay within training distribution.
# The history is passed through as a list of messages, this should allow the LLM to more easily understand what is going on.
# The special tokens and separators let the LLM more easily disregard no longer relevant past messages.
# The last message is dynamically created and has a detailed description of the actual task.
# This is based on the assumption that users give much more varied requests in their prompts and LLMs are well adjusted to this.
# The proximity of the instructions and the lack of any breaks should also let the LLM follow the task more clearly.
#
# For document verification, the history is not included as the queries should ideally be standalone enough.
# To keep it simple, it is just a single simple prompt.


SEMANTIC_QUERY_REPHRASE_SYSTEM_PROMPT = """
You are an assistant that reformulates the last user message into a standalone, self-contained query suitable for \
semantic search. Your goal is to output a single natural language query that captures the full meaning of the user's \
most recent message. It should be fully semantic and natural language unless the user query is already a keyword query. \
When relevant, you bring in context from the history or knowledge about the user.

The current date is {current_date}.
"""

SEMANTIC_QUERY_REPHRASE_USER_PROMPT = """
Given the chat history and the final user query, provide a standalone query that is as representative of the user query \
as possible. In most cases, it should be exactly the same as the last user query. \
It should be fully semantic and natural language unless the user query is already a keyword query. \
Focus on the last user message, in most cases the history and extra context should be ignored.

For a query like "What are the use cases for product X", your output should remain "What are the use cases for product X". \
It should remain semantic, and as close to the original query as possible. There is nothing additional needed \
from the history or that should be removed / replaced from the query.

For modifications, you can:
1. Insert relevant context from the chat history. For example:
"How do I set it up?" -> "How do I set up software Y?" (assuming the conversation was about software Y)

2. Remove asks or requests not related to the searching. For example:
"Can you summarize the calls with example company" -> "calls with example company"
"Can you find me the document that goes over all of the software to set up on an engineer's first day?" -> \
"all of the software to set up on an engineer's first day"

3. Fill in relevant information about the user. For example:
"What document did I write last week?" -> "What document did John Doe write last week?" (assuming the user is John Doe)
{additional_context}
=========================

Final user query:
{user_query}

CRITICAL: ONLY provide the standalone query and nothing else.
""".strip()


KEYWORD_REPHRASE_SYSTEM_PROMPT = """
You are an assistant that reformulates the last user message into a set of standalong keyword queries suitable for a keyword \
search engine. Your goal is to output keyword queries that optimize finding relevant documents to answer the user query. \
When relevant, you bring in context from the history or knowledge about the user.

The current date is {current_date}.
"""


KEYWORD_REPHRASE_USER_PROMPT = """
Given a chat history and a follow up user input, provide a set of keyword only queries that can help find relevant documents. \
Provide a single query per line (where each query consists of one or more keywords). \
The queries must be purely keywords and not contain any natural language. \
The each query should have as few keywords as necessary to represent the user's search intent.

Guidelines:
- Do not provide more than 3 queries.
- Do not replace or expand niche, proprietary, or obscure terms
- Focus on the last user message, in most cases the history and any extra context should be ignored.
{additional_context}

=========================

Final user query:
{user_query}

CRITICAL: ONLY provide the keyword queries, one set of keywords per line and nothing else.
""".strip()


REPHRASE_CONTEXT_PROMPT = """
In most cases the following additional context is not needed. If relevant, here is some information about the user:
{user_info}

Here are some memories about the user:
{memories}
"""


# Some models are trained heavily to reason in the actual output so we allow some flexibility in the prompt
# Downstream of the model, we will attempt to parse the output to extract the number.
DOCUMENT_CONTEXT_SELECTION_PROMPT = """
Given a main section of a document and surrounding sections, choose between the following situations:
1. The main section and surrounding sections are not useful for answer the user query. \
They are either not relevant or related but about something else and could cause confusion for the final answer generation.
2. The main section is useful and contains all of the relevant information; the surrounding sections are not useful.
3. The main section and surrounding sections are all useful for answering the user query. \
All of the sections should be passed back for generating the final answer.
4. The main section and surrounding sections are all useful and likely including the rest of the document will provided \
even more valuable context. This is a very on relevant document and should be included in full.

Do not assume every document is relevant to the query, many documents may be loosely related but actually misleading. \
Be sure to remove those by classifying them as type 1.

Main Section:
```
{main_section}
```

Section Above:
```
{section_above}
```

Section Below:
```
{section_below}
```

Search Query:
```
{search_query}
```

Try to answer with the number of the situation most applicable to the sections.
If you need to reason about it, your final output should end with the number (1, 2, 3, or 4).
""".strip()
