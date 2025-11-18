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


DOCUMENT_SELECTION_PROMPT = """
Select the most relevant document sections for the search query (maximum 10).

# Document Sections
```
{formatted_doc_sections}
```

# User Query
```
{user_query}
```

# Selection Criteria
- Choose sections most relevant to answering the query.
- Include sections from highly relevant documents (the full document will be expanded later).
- It is ok to select multiple sections from the same document.

# Output Format
Return ONLY section IDs as a comma-separated list, ordered by relevance:
[most_relevant_id, second_most_relevant_id, ...]

Section IDs:
""".strip()


# Some models are trained heavily to reason in the actual output so we allow some flexibility in the prompt
# Downstream of the model, we will attempt to parse the output to extract the number.
# This inference will not have a system prompt as it's a single message task more like the traditional ones.
# LLMs should do better with just this type of next word prediction.
DOCUMENT_CONTEXT_SELECTION_PROMPT = """
Analyze the relevance of document sections to a search query and classify according to the categories \
described at the end of the prompt.

# Section Above:
```
{section_above}
```

# Main Section:
```
{main_section}
```

# Section Below:
```
{section_below}
```

# User Query:
```
{user_query}
```

# Classification Categories:
**1 - NOT_RELEVANT**
- Main section and surrounding sections do NOT help answer the query.
- Appears on topic but refers to a different context or subject.
- No meaningful information related to the query.

**2 - MAIN_SECTION_ONLY**
- Main section contains useful information for the query.
- Adjacent sections do not provide additional directly relevant information.

**3 - INCLUDE_ADJACENT_SECTIONS**
- The main section AND adjacent sections are all useful for answering the user query.
- The surrounding sections provide relevant information that does not exist in the main section.
- Even if only 1 of the adjacent sections is useful or there is a small piece in either that is useful.

**4 - INCLUDE_FULL_DOCUMENT**
- Sections shown are highly relevant to the query.
- Document appears to be very pertinent to the query topic.
- Additional unseen sections likely contain valuable related information.

## Additional Decision Notes
- If only a small piece of the document is useful - use classification 2 or 3, do not use 1.
- If the document is very on topic and provides additional context that might be useful in \
combination with other documents - use classification 2, 3 or 4, do not use 1.
- A section may appear on topic but could refer to a different context or subject don't assume relevance. \
In this case, use this classification.
- It is important to avoid conflating different contexts and subjects - if the document is related to the query but not about \
the correct subject, use classification 1.

CRITICAL: ONLY output the NUMBER of the situation most applicable to the query and sections provided (1, 2, 3, or 4).

Situation Number:
""".strip()
