from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_ANSWER_SEPARATOR,
)

# Standards
SEPARATOR_LINE = "-------"
SEPARATOR_LINE_LONG = "---------------"
UNKNOWN_ANSWER = "I do not have enough information to answer this question."
NO_RECOVERED_DOCS = "No relevant information recovered"
YES = "yes"
NO = "no"
# Framing/Support/Template Prompts
HISTORY_FRAMING_PROMPT = f"""
For more context, here is the history of the conversation so far that preceded this question:
{SEPARATOR_LINE}
{{history}}
{SEPARATOR_LINE}
""".strip()


COMMON_RAG_RULES = f"""
IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer. \
You may give some additional facts you learned, but do not try to invent an answer.

 - If the information is empty or irrelevant, just say "{UNKNOWN_ANSWER}".

 - If the information is relevant but not fully conclusive, provide an answer to the extent you can but also specify that \
the information is not conclusive and why.

- When constructing/considering categories, focus less on the question and more on the context actually provided! \
Example: if the question is about the products of company A, and the content provided lists a number of products, \
do automatically NOT ASSUME that those belong to company A!  So you cannot list those as products of company A, despite \
the fact that the question is about company A's products. What you should say instead is maybe something like \
"Here are a number of products, but I cannot say whether some or all of them belong to company A: \
<proceed with listing the products>". It is ABSOLUTELY ESSENTIAL that the answer constructed reflects \
actual knowledge. For that matter, also consider the title of the document and other information that may be \
provided. If that does not make it clear that - in the example above - the products belong to company A, \
then do not list them as products of company A, just maybe as "A list products that may not necessarily \
belong to company A". THIS IS IMPORTANT!

- Related, if the context provides a list of items with associated data or other information that seems \
to align with the categories in the question, but does not specify whether the items or the information is \
specific to the exact requested category, then present the information with a disclaimer. Use a title such as \
"I am not sure whether these items (or the information provided) is specific to [relevant category] or whether \
these are all [specific group], but I found this information may be helpful:" \
followed by the list of items and associated data/or information discovered.

 - Do not group together items amongst one headline where not all items belong to the category of the headline! \
(Example: "Products used by Company A" where some products listed are not built by Company A, but other companies,
or it is not clear that the products are built by Company A). Only state what you know for sure!

 - Do NOT perform any calculations in the answer! Just report on facts.

 - If appropriate, organizing your answer in bullet points is often useful.
""".strip()

ASSISTANT_SYSTEM_PROMPT_DEFAULT = "You are an assistant for question-answering tasks."

ASSISTANT_SYSTEM_PROMPT_PERSONA = f"""
You are an assistant for question-answering tasks. Here is more information about you:
{SEPARATOR_LINE}
{{persona_prompt}}
{SEPARATOR_LINE}
""".strip()


SUB_QUESTION_ANSWER_TEMPLATE = f"""
Sub-Question: Q{{sub_question_num}}
Question:
{{sub_question}}
{SEPARATOR_LINE}
Answer:
{{sub_answer}}
""".strip()


SUB_QUESTION_ANSWER_TEMPLATE_REFINED = f"""
Sub-Question: Q{{sub_question_num}}
Type: {{sub_question_type}}
Sub-Question:
{SEPARATOR_LINE}
{{sub_question}}
{SEPARATOR_LINE}
Answer:
{SEPARATOR_LINE}
{{sub_answer}}
{SEPARATOR_LINE}
""".strip()


# Step/Utility Prompts
# Note this one should always be used with the ENTITY_TERM_EXTRACTION_PROMPT_JSON_EXAMPLE
ENTITY_TERM_EXTRACTION_PROMPT = f"""
Based on the original question and some context retrieved from a dataset, please generate a list of \
entities (e.g. companies, organizations, industries, products, locations, etc.), terms and concepts \
(e.g. sales, revenue, etc.) that are relevant for the question, plus their relations to each other.

Here is the original question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

And here is the context retrieved:
{SEPARATOR_LINE}
{{context}}
{SEPARATOR_LINE}

Please format your answer as a json object in the following format:
""".lstrip()

ENTITY_TERM_EXTRACTION_PROMPT_JSON_EXAMPLE = """
{
    "retrieved_entities_relationships": {
        "entities": [
            {
                "entity_name": "<assign a name for the entity>",
                "entity_type": "<specify a short type name for the entity, such as 'company', 'location',...>"
            }
        ],
        "relationships": [
            {
                "relationship_name": "<assign a name for the relationship>",
                "relationship_type": "<specify a short type name for the relationship, such as 'sales_to', 'is_location_of',...>",
                "relationship_entities": ["<related entity name 1>", "<related entity name 2>", "..."]
            }
        ],
        "terms": [
            {
                "term_name": "<assign a name for the term>",
                "term_type": "<specify a short type name for the term, such as 'revenue', 'market_share',...>",
                "term_similar_to": ["<list terms that are similar to this term>"]
            }
        ]
    }
}
""".strip()


HISTORY_CONTEXT_SUMMARY_PROMPT = f"""
{{persona_specification}}

Your task now is to summarize the key parts of the history of a conversation between a user and an agent. \
The summary has two purposes:
  1) providing the suitable context for a new question, and
  2) To capture the key information that was discussed and that the user may have a follow-up question about.

Here is the question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

And here is the history:
{SEPARATOR_LINE}
{{history}}
{SEPARATOR_LINE}

Please provide a summarized context from the history so that the question makes sense and can \
- with suitable extra information - be answered.

Do not use more than three or four sentences.

History summary:
""".strip()


# INITIAL PHASE
# Sub-question
# Intentionally left a copy in case we want to modify this one differently
INITIAL_QUESTION_DECOMPOSITION_PROMPT = f"""
Please create a list of no more than 3 sub-questions whose answers would help to inform the answer \
to the initial question.

The purpose for these sub-questions could be:
  1) decomposition to isolate individual entities (i.e., 'compare sales of company A and company B' -> \
['what are sales for company A', 'what are sales for company B'])

  2) clarification and/or disambiguation of ambiguous terms (i.e., 'what is our success with company A' -> \
['what are our sales with company A','what is our market share with company A', \
'is company A a reference customer for us', etc.])

  3) if a term or a metric is essentially clear, but it could relate to various aspects of an entity and you \
are generally familiar with the entity, then you can create sub-questions that are more \
specific (i.e.,  'what do we do to improve product X' -> 'what do we do to improve scalability of product X', \
'what do we do to improve performance of product X', 'what do we do to improve stability of product X', ...)

  4) research individual questions and areas that should really help to ultimately answer the question.

Important:

 - Each sub-question should lend itself to be answered by a RAG system. Correspondingly, phrase the question \
in a way that is amenable to that. An example set of sub-questions based on an initial question could look like this:
'what can I do to improve the performance of workflow X' -> \
'what are the settings affecting performance for workflow X', 'are there complaints and bugs related to \
workflow X performance', 'what are performance benchmarks for workflow X', ...

 - Consequently, again, don't just decompose, but make sure that the sub-questions have the proper form. I.e., no \
 'I', etc.

 - Do not(!) create sub-questions that are clarifying question to the person who asked the question, \
like making suggestions or asking the user for more information! This is not useful for the actual \
question-answering process! You need to take the information from the user as it is given to you! \
For example, should the question be of the type 'why does product X perform poorly for customer A', DO NOT create a \
sub-question of the type 'what are the settings that customer A uses for product X?'! A valid sub-question \
could rather be 'which settings for product X have been shown to lead to poor performance for customers?'


And here is the initial question to create sub-questions for, so that you have the full context:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

{{history}}

Do NOT include any text in your answer outside of the list of sub-questions!
Please formulate your answer as a newline-separated list of questions like so (and please ONLY ANSWER WITH THIS LIST! Do not \
add any explanations or other text!):

 <sub-question>
 <sub-question>
 <sub-question>
 ...

Answer:
""".strip()

# INITIAL PHASE - AWARE OF REFINEMENT
# Sub-question
# Suggest augmenting question generation as well, that a future refinement phase could use
# to generate new questions
# Intentionally left a copy in case we want to modify this one differently
INITIAL_QUESTION_DECOMPOSITION_PROMPT_ASSUMING_REFINEMENT = f"""
Please create a list of no more than 3 sub-questions whose answers would help to inform the answer \
to the initial question.

The purpose for these sub-questions could be:
  1) decomposition to isolate individual entities (i.e., 'compare sales of company A and company B' -> \
['what are sales for company A', 'what are sales for company B'])

  2) clarification and/or disambiguation of ambiguous terms (i.e., 'what is our success with company A' -> \
['what are our sales with company A','what is our market share with company A', \
'is company A a reference customer for us', etc.])

  3) if a term or a metric is essentially clear, but it could relate to various aspects of an entity and you \
are generally familiar with the entity, then you can create sub-questions that are more \
specific (i.e.,  'what do we do to improve product X' -> 'what do we do to improve scalability of product X', \
'what do we do to improve performance of product X', 'what do we do to improve stability of product X', ...)

  4) research individual questions and areas that should really help to ultimately answer the question.

  5) if meaningful, find relevant facts that may inform another set of sub-questions generate after the set you \
create now are answered. Example: 'which products have we implemented at company A, and is this different to \
its competitors?'  could potentially create sub-questions 'what products have we implemented at company A', \
and 'who are the competitors of company A'. The additional round of sub-question generation which sees the \
answers for this initial round of sub-question creation could then use the answer to the second sub-question \
(which could be 'company B and C are competitors of company A') to then ask 'which products have we implemented \
at company B', 'which products have we implemented at company C'...

Important:

 - Each sub-question should lend itself to be answered by a RAG system. Correspondingly, phrase the question \
in a way that is amenable to that. An example set of sub-questions based on an initial question could look like this:
'what can I do to improve the performance of workflow X' -> \
'what are the settings affecting performance for workflow X', 'are there complaints and bugs related to \
workflow X performance', 'what are performance benchmarks for workflow X', ...

 - Consequently, again, don't just decompose, but make sure that the sub-questions have the proper form. I.e., no \
 'I', etc.

 - Do not(!) create sub-questions that are clarifying question to the person who asked the question, \
like making suggestions or asking the user for more information! This is not useful for the actual \
question-answering process! You need to take the information from the user as it is given to you! \
For example, should the question be of the type 'why does product X perform poorly for customer A', DO NOT create a \
sub-question of the type 'what are the settings that customer A uses for product X?'! A valid sub-question \
could rather be 'which settings for product X have been shown to lead to poor performance for customers?'


And here is the initial question to create sub-questions for:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

{{history}}

Do NOT include any text in your answer outside of the list of sub-questions!
Please formulate your answer as a newline-separated list of questions like so (and please ONLY ANSWER WITH THIS LIST! Do not \
add any explanations or other text!):

 <sub-question>
 <sub-question>
 <sub-question>
 ...

Answer:
""".strip()


# TODO: combine shared pieces with INITIAL_QUESTION_DECOMPOSITION_PROMPT
INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH = f"""
Please create a list of no more than 3 sub-questions whose answers would help to inform the answer \
to the initial question.

The purpose for these sub-questions could be:
  1) decomposition to isolate individual entities (i.e., 'compare sales of company A and company B' -> \
['what are sales for company A', 'what are sales for company B'])

  2) clarification and/or disambiguation of ambiguous terms (i.e., 'what is our success with company A' -> \
['what are our sales with company A','what is our market share with company A', \
'is company A a reference customer for us', etc.])

  3) if a term or a metric is essentially clear, but it could relate to various aspects of an entity and you \
are generally familiar with the entity, then you can create sub-questions that are more \
specific (i.e.,  'what do we do to improve product X' -> 'what do we do to improve scalability of product X', \
'what do we do to improve performance of product X', 'what do we do to improve stability of product X', ...)

  4) research individual questions and areas that should really help to ultimately answer the question.

Important:

 - Each sub-question should lend itself to be answered by a RAG system. Correspondingly, phrase the question \
in a way that is amenable to that. An example set of sub-questions based on an initial question could look like this:
'what can I do to improve the performance of workflow X' -> \
'what are the settings affecting performance for workflow X', 'are there complaints and bugs related to \
workflow X performance', 'what are performance benchmarks for workflow X', ...

 - Consequently, again, don't just decompose, but make sure that the sub-questions have the proper form. I.e., no \
 'I', etc.

 - Do not(!) create sub-questions that are clarifying question to the person who asked the question, \
like making suggestions or asking the user for more information! This is not useful for the actual \
question-answering process! You need to take the information from the user as it is given to you! \
For example, should the question be of the type 'why does product X perform poorly for customer A', DO NOT create a \
sub-question of the type 'what are the settings that customer A uses for product X?'! A valid sub-question \
could rather be 'which settings for product X have been shown to lead to poor performance for customers?'


To give you some context, you will see below also some documents that may relate to the question. Please only \
use this information to learn what the question is approximately asking about, but do not focus on the details \
to construct the sub-questions! Also, some of the entities, relationships and terms that are in the dataset may \
not be in these few documents, so DO NOT focus too much on the documents when constructing the sub-questions! \
Decomposition and disambiguations are most important!

Here are the sample docs to give you some context:
{SEPARATOR_LINE}
{{sample_doc_str}}
{SEPARATOR_LINE}

And here is the initial question to create sub-questions for, so that you have the full context:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

{{history}}

Do NOT include any text in your answer outside of the list of sub-questions!\
Please formulate your answer as a newline-separated list of questions like so (and please ONLY ANSWER WITH THIS LIST! Do not \
add any explanations or other text!):

 <sub-question>
 <sub-question>
 <sub-question>
 ...

Answer:
""".strip()

INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH_ASSUMING_REFINEMENT = f"""
Please create a list of no more than 3 sub-questions whose answers would help to inform the answer \
to the initial question.

The purpose for these sub-questions could be:
  1) decomposition to isolate individual entities (i.e., 'compare sales of company A and company B' -> \
['what are sales for company A', 'what are sales for company B'])

  2) clarification and/or disambiguation of ambiguous terms (i.e., 'what is our success with company A' -> \
['what are our sales with company A','what is our market share with company A', \
'is company A a reference customer for us', etc.])

  3) if a term or a metric is essentially clear, but it could relate to various aspects of an entity and you \
are generally familiar with the entity, then you can create sub-questions that are more \
specific (i.e.,  'what do we do to improve product X' -> 'what do we do to improve scalability of product X', \
'what do we do to improve performance of product X', 'what do we do to improve stability of product X', ...)

  4) research individual questions and areas that should really help to ultimately answer the question.

  5) if applicable and useful, consider using sub-questions to gather relevant information that can inform a \
subsequent set of sub-questions. The answers to your initial sub-questions will be available when generating \
the next set.
For example, if you start with the question, "Which products have we implemented at Company A, and how does \
this compare to its competitors?" you might first create sub-questions like "What products have we implemented \
at Company A?" and "Who are the competitors of Company A?"
The answer to the second sub-question, such as "Company B and C are competitors of Company A," can then be used \
to generate more specific sub-questions in the next round, like "Which products have we implemented at Company B?" \
and "Which products have we implemented at Company C?"

You'll be the judge!

Important:

 - Each sub-question should lend itself to be answered by a RAG system. Correspondingly, phrase the question \
in a way that is amenable to that. An example set of sub-questions based on an initial question could look like this:
'what can I do to improve the performance of workflow X' -> \
'what are the settings affecting performance for workflow X', 'are there complaints and bugs related to \
workflow X performance', 'what are performance benchmarks for workflow X', ...

 - Consequently, again, don't just decompose, but make sure that the sub-questions have the proper form. I.e., no \
 'I', etc.

 - Do not(!) create sub-questions that are clarifying question to the person who asked the question, \
like making suggestions or asking the user for more information! This is not useful for the actual \
question-answering process! You need to take the information from the user as it is given to you! \
For example, should the question be of the type 'why does product X perform poorly for customer A', DO NOT create a \
sub-question of the type 'what are the settings that customer A uses for product X?'! A valid sub-question \
could rather be 'which settings for product X have been shown to lead to poor performance for customers?'

To give you some context, you will see below also some documents that may relate to the question. Please only \
use this information to learn what the question is approximately asking about, but do not focus on the details \
to construct the sub-questions! Also, some of the entities, relationships and terms that are in the dataset may \
not be in these few documents, so DO NOT focus too much on the documents when constructing the sub-questions! \
Decomposition and disambiguations are most important!

Here are the sample docs to give you some context:
{SEPARATOR_LINE}
{{sample_doc_str}}
{SEPARATOR_LINE}

And here is the initial question to create sub-questions for, so that you have the full context:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

{{history}}

Do NOT include any text in your answer outside of the list of sub-questions!\
Please formulate your answer as a newline-separated list of questions like so (and please ONLY ANSWER WITH THIS LIST! Do not \
add any explanations or other text!):

 <sub-question>
 <sub-question>
 <sub-question>
 ...

Answer:
""".strip()

# Retrieval
QUERY_REWRITING_PROMPT = f"""
Please convert the initial user question into a 2-3 more appropriate short and pointed search queries for \
retrieval from a document store. Particularly, try to think about resolving ambiguities and make the search \
queries more specific, enabling the system to search more broadly.

Also, try to make the search queries not redundant, i.e. not too similar!

Here is the initial question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Do NOT include any text in your answer outside of the list of queries!\
Formulate the queries separated by newlines (Do not say 'Query 1: ...', just write the querytext) as follows:
<query 1>
<query 2>
...

Queries:
""".strip()


DOCUMENT_VERIFICATION_PROMPT = f"""
Determine whether the following document text contains data or information that is potentially relevant \
for a question. It does not have to be fully relevant, but check whether it has some information that \
would help - possibly in conjunction with other documents - to address the question.

Be careful that you do not use a document where you are not sure whether the text applies to the objects \
or entities that are relevant for the question. For example, a book about chess could have long passage \
discussing the psychology of chess without - within the passage - mentioning chess. If now a question \
is asked about the psychology of football, one could be tempted to use the document as it does discuss \
psychology in sports. However, it is NOT about football and should not be deemed relevant. Please \
consider this logic.

DOCUMENT TEXT:
{SEPARATOR_LINE}
{{document_content}}
{SEPARATOR_LINE}

Do you think that this document text is useful and relevant to answer the following question?

QUESTION:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please answer with exactly and only a '{YES}' or '{NO}'. Do NOT include any other text in your response:

Answer:
""".strip()


# Sub-Question Answer Generation
SUB_QUESTION_RAG_PROMPT = f"""
Use the context provided below - and only the provided context - to answer the given question. \
(Note that the answer is in service of answering a broader question, given below as 'motivation').

Make sure that you keep all relevant information, specifically as it concerns the ultimate goal. \
(But keep other details as well.)

{COMMON_RAG_RULES}

 - Make sure that you only state what you actually can positively learn from the provided context! Particularly \
don't make assumptions!  Example: if i) a question you should answer is asking for products of companies that \
are competitors of company A, and ii) the context mentions products of companies A, B, C, D, E, etc., do NOT assume \
that B, C, D, E, etc. are competitors of A! All you know is that these are products of a number of companies, and you \
would have to rely on another question - that you do not have access to - to learn which companies are competitors of A.
Correspondingly, you should not say that these are the products of competitors of A, but rather something like \
"Here are some products of various companies".

It is critical that you provide inline citations in the format [D1], [D2], [D3], etc! Please use format [D1][D2] and NOT \
[D1, D2] format if you cite two or more documents together! \
It is important that the citation is close to the information it supports. \
Proper citations are very important to the user!

Here is the document context for you to consider:
{SEPARATOR_LINE}
{{context}}
{SEPARATOR_LINE}

For your general information, here is the ultimate motivation for the question you need to answer:
{SEPARATOR_LINE}
{{original_question}}
{SEPARATOR_LINE}

And here is the actual question I want you to answer based on the context above (with the motivation in mind):
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please keep your answer brief and concise, and focus on facts and data. (Again, only state what you see in the documents \
for sure and communicate if/in what way this may or may not relate to the question you need to answer!)

Answer:
""".strip()


SUB_ANSWER_CHECK_PROMPT = f"""
Determine whether the given answer addresses the given question. \
Please do not use any internal knowledge you may have - just focus on whether the answer \
as given seems to largely address the question as given, or at least addresses part of the question.

Here is the question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Here is the suggested answer:
{SEPARATOR_LINE}
{{base_answer}}
{SEPARATOR_LINE}

Does the suggested answer address the question? Please answer with "{YES}" or "{NO}".
""".strip()


# Initial Answer Generation
INITIAL_ANSWER_PROMPT_W_SUB_QUESTIONS = f"""
{{persona_specification}}

Use the information provided below - and only the provided information - to answer the provided main question.

The information provided below consists of:
  1) a number of answered sub-questions - these are very important to help you organize your thoughts and your answer
  2) a number of documents that are deemed relevant for the question.

{{history}}

It is critical that you provide proper inline citations to documents in the format [D1], [D2], [D3], etc.! \
It is important that the citation is close to the information it supports. If you have multiple citations that support \
a fact, please cite for example as [D1][D3], or [D2][D4], etc. \
Feel free to also cite sub-questions in addition to documents, but make sure that you have documents cited with the \
sub-question citation. If you want to cite both a document and a sub-question, please use [D1][Q3], or [D2][D7][Q4], etc. \
Again, please NEVER cite sub-questions without a document citation! Proper citations are very important for the user!

{COMMON_RAG_RULES}

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones, \
or assumptions you made.

Here is the contextual information:
{SEPARATOR_LINE_LONG}

*Answered Sub-questions (these should really matter!):
{SEPARATOR_LINE}
{{answered_sub_questions}}
{SEPARATOR_LINE}

And here are relevant document information that support the sub-question answers, or that are relevant for the actual question:
{SEPARATOR_LINE}
{{relevant_docs}}
{SEPARATOR_LINE}

And here is the question I want you to answer based on the information above:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please keep your answer brief and concise, and focus on facts and data. (Again, only state what you see in the documents for \
sure and communicate if/in what way this may or may not relate to the question you need to answer! Use the answered \
sub-questions as well, but be cautious and reconsider the docments again for validation.)

Answer:
""".strip()


# Used if sub_question_answer_str is empty
INITIAL_ANSWER_PROMPT_WO_SUB_QUESTIONS = f"""
{{answered_sub_questions}}{{persona_specification}}

Use the information provided below - and only the provided information - to answer the provided question. \
The information provided below consists of a number of documents that were deemed relevant for the question.

{{history}}

{COMMON_RAG_RULES}

Again, you should be sure that the answer is supported by the information provided!

It is critical that you provide proper inline citations to documents in the format [D1], [D2], [D3], etc! \
It is important that the citation is close to the information it supports. \
If you have multiple citations, please cite for example as [D1][D3], or [D2][D4], etc. \
Citations are very important for the user!

Here is the relevant context information:
{SEPARATOR_LINE}
{{relevant_docs}}
{SEPARATOR_LINE}

And here is the question I want you to answer based on the context above:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please keep your answer brief and concise, and focus on facts and data. (Again, only state what you see in the documents \
for sure and communicate if/in what way this may or may not relate to the question you need to answer!)

Answer:
""".strip()


# REFINEMENT PHASE
REFINEMENT_QUESTION_DECOMPOSITION_PROMPT = f"""
An initial user question needs to be answered. An initial answer has been provided but it wasn't quite good enough. \
Also, some sub-questions had been answered and this information has been used to provide the initial answer. \
Some other subquestions may have been suggested based on little knowledge, but they were not directly answerable. \
Also, some entities, relationships and terms are given to you so that you have an idea of how the available data looks like.

Your role is to generate 2-4 new sub-questions that would help to answer the initial question, considering:

1) The initial question
2) The initial answer that was found to be unsatisfactory
3) The sub-questions that were answered
4) The sub-questions that were suggested but not answered
5) The entities, relationships and terms that were extracted from the context

The individual questions should be answerable by a good RAG system. So a good idea would be to use the sub-questions to \
resolve ambiguities and/or to separate the question for different entities that may be involved in the original question, \
but in a way that does not duplicate questions that were already tried.

Additional Guidelines:
- The sub-questions should be specific to the question and provide richer context for the question, resolve ambiguities, \
or address shortcoming of the initial answer
- Each sub-question - when answered - should be relevant for the answer to the original question
- The sub-questions should be free from comparisons, ambiguities,judgements, aggregations, or any other complications that \
may require extra context
- The sub-questions MUST have the full context of the original question so that it can be executed by a RAG system \
independently without the original question available
    Example:
    - initial question: "What is the capital of France?"
    - bad sub-question: "What is the name of the river there?"
    - good sub-question: "What is the name of the river that flows through Paris?"
- For each sub-question, please also provide a search term that can be used to retrieve relevant documents from a document store.
- Consider specifically the sub-questions that were suggested but not answered. This is a sign that they are not answerable \
with the available context, and you should not ask similar questions.
 - Do not(!) create sub-questions that are clarifying question to the person who asked the question, \
like making suggestions or asking the user for more information! This is not useful for the actual \
question-answering process! You need to take the information from the user as it is given to you! \
For example, should the question be of the type 'why does product X perform poorly for customer A', DO NOT create a \
sub-question of the type 'what are the settings that customer A uses for product X?'! A valid sub-question \
could rather be 'which settings for product X have been shown to lead to poor performance for customers?'

Here is the initial question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}
{{history}}

Here is the initial sub-optimal answer:
{SEPARATOR_LINE}
{{base_answer}}
{SEPARATOR_LINE}

Here are the sub-questions that were answered:
{SEPARATOR_LINE}
{{answered_sub_questions}}
{SEPARATOR_LINE}

Here are the sub-questions that were suggested but not answered:
{SEPARATOR_LINE}
{{failed_sub_questions}}
{SEPARATOR_LINE}

And here are the entities, relationships and terms extracted from the context:
{SEPARATOR_LINE}
{{entity_term_extraction_str}}
{SEPARATOR_LINE}

Please generate the list of good, fully contextualized sub-questions that would help to address the main question. \
Specifically pay attention also to the entities, relationships and terms extracted, as these indicate what type of \
objects/relationships/terms you can ask about! Do not ask about entities, terms or relationships that are not mentioned in the \
'entities, relationships and terms' section.

Again, please find questions that are NOT overlapping too much with the already answered sub-questions or those that \
already were suggested and failed. In other words - what can we try in addition to what has been tried so far?

Generate the list of questions separated by one new line like this (and please ONLY ANSWER WITH THIS LIST! Do not \
add any explanations or other text!):

<sub-question 1>
<sub-question 2>
<sub-question 3>
...""".strip()

REFINEMENT_QUESTION_DECOMPOSITION_PROMPT_W_INITIAL_SUBQUESTION_ANSWERS = f"""
An initial user question needs to be answered. An initial answer has been provided but it wasn't quite good enough. \
Also, some sub-questions had been answered and this information has been used to provide the initial answer. \
Some other subquestions may have been suggested based on little knowledge, but they were not directly answerable. \
Also, some entities, relationships and terms are given to you so that you have an idea of how the available data looks like.

Your role is to generate 2-4 new sub-questions that would help to answer the initial question, considering:

1) The initial question
2) The initial answer that was found to be unsatisfactory
3) The sub-questions that were answered AND their answers
4) The sub-questions that were suggested but not answered (and that you should not repeat!)
5) The entities, relationships and terms that were extracted from the context

The individual questions should be answerable by a good RAG system. So a good idea would be to use the sub-questions to \
resolve ambiguities and/or to separate the question for different entities that may be involved in the original question, \
but in a way that does not duplicate questions that were already tried.

Additional Guidelines:

- The new sub-questions should be specific to the question and provide richer context for the question, resolve ambiguities, \
or address shortcoming of the initial answer

- Each new sub-question - when answered - should be relevant for the answer to the original question

- The new sub-questions should be free from comparisons, ambiguities,judgements, aggregations, or any other complications that \
may require extra context

- The new sub-questions MUST have the full context of the original question so that it can be executed by a RAG system \
independently without the original question available
    Example:
    - initial question: "What is the capital of France?"
    - bad sub-question: "What is the name of the river there?"
    - good sub-question: "What is the name of the river that flows through Paris?"

    - For each new sub-question, please also provide a search term that can be used to retrieve relevant documents \
from a document store.

- Consider specifically the sub-questions that were suggested but not answered. This is a sign that they are not answerable \
with the available context, and you should not ask similar questions.

- Pay attention to the answers of previous sub-question to make your sub-questions more specific! \
Often the initial sub-questions were set up to give you critical information that you should use to generate new sub-questions.\
For example, if the answer to a an earlier sub-question is \
'Company B and C are competitors of Company A', you should not ask now a new sub-question involving the term 'competitors', \
as you already have the information to create a more precise question - you should instead explicitly reference \
'Company B' and 'Company C' in your new sub-questions, as these are the competitors based on the previously answered question.

- Be precise(!) and don't make inferences you cannot be sure about! For example, in the previous example \
where Company B and Company C were identified as competitors of Company A, and then you also get information on \
companies D and E, do not make the inference that these are also competitors of Company A! Stick to the information you have!
(Also, don't assume that companies B and C arethe only competitors of A, unless stated!)

- Do not(!) create sub-questions that are clarifying question *to the person who asked the question*, \
like making suggestions or asking the user for more information! This is not useful for the actual \
question-answering process! You need to take the information from the user as it is given to you! \
For example, should the question be of the type 'why does product X perform poorly for customer A', DO NOT create a \
sub-question of the type 'what are the settings that customer A uses for product X?'! A valid sub-question \
could rather be 'which settings for product X have been shown to lead to poor performance for customers?'

Here is the initial question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}
{{history}}

Here is the initial sub-optimal answer:
{SEPARATOR_LINE}
{{base_answer}}
{SEPARATOR_LINE}

Here are the sub-questions that were answered:
{SEPARATOR_LINE}
{{answered_subquestions_with_answers}}
{SEPARATOR_LINE}

Here are the sub-questions that were suggested but not answered:
{SEPARATOR_LINE}
{{failed_sub_questions}}
{SEPARATOR_LINE}

And here are the entities, relationships and terms extracted from the context:
{SEPARATOR_LINE}
{{entity_term_extraction_str}}
{SEPARATOR_LINE}

Please generate the list of good, fully contextualized sub-questions that would help to address the main question. \
Specifically pay attention also to the entities, relationships and terms extracted, as these indicate what type of \
objects/relationships/terms you can ask about! Do not ask about entities, terms or relationships that are not mentioned \
in the 'entities, relationships and terms' section.

Again, please find questions that are NOT overlapping too much with the already answered sub-questions or those that \
already were suggested and failed. In other words - what can we try in addition to what has been tried so far?

Generate the list of questions separated by one new line like this (and please ONLY ANSWER WITH THIS LIST! Do not \
add any explanations or other text!):

<sub-question 1>
<sub-question 2>
<sub-question 3>
...""".strip()


REFINED_ANSWER_PROMPT_W_SUB_QUESTIONS = f"""
{{persona_specification}}

Your task is to improve on a given answer to a question, as the initial answer was found to be lacking in some way.

Use the information provided below - and only the provided information - to write your new and improved answer.

The information provided below consists of:
  1) an initial answer that was given but likely found to be lacking in some way.
  2) a number of answered sub-questions - these are very important(!) and definitely should help you to answer the main \
question. Note that the sub-questions have a type, 'initial' and 'refined'. The 'initial' ones were available for the \
creation of the initial answer, but the 'refined' were not, they are new. So please use the 'refined' sub-questions in \
particular to update/extend/correct/enrich the initial answer and to add more details/new facts!
  3) a number of documents that were deemed relevant for the question. This is the context that you use largely for citations \
(see below). So consider the answers to the sub-questions as guidelines to construct your new answer, but make sure you cite \
the relevant document for a fact!

It is critical that you provide proper inline citations to documents in the format [D1], [D2], [D3], etc! \
Please use format [D1][D2] and NOT [D1, D2] format if you cite two or more documents together! \
It is important that the citation is close to the information it supports. \
DO NOT just list all of the citations at the very end. \
Feel free to also cite sub-questions in addition to documents, \
but make sure that you have documents cited with the sub-question citation. \
If you want to cite both a document and a sub-question, please use [D1][Q3], or [D2][D7][Q4], etc. and always place the \
document citation before the sub-question citation. Again, please NEVER cite sub-questions without a document citation! \
Proper citations are very important for the user!

{{history}}

{COMMON_RAG_RULES}

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones, \
or assumptions you made.

Here is the contextual information:
{SEPARATOR_LINE_LONG}

*Initial Answer that was found to be lacking:
{SEPARATOR_LINE}
{{initial_answer}}
{SEPARATOR_LINE}

*Answered Sub-questions (these should really help you to research your answer! They also contain questions/answers that \
were not available when the original answer was constructed):
{{answered_sub_questions}}

And here are the relevant documents that support the sub-question answers, and that are relevant for the actual question:
{SEPARATOR_LINE}
{{relevant_docs}}
{SEPARATOR_LINE}

Lastly, here is the main question I want you to answer based on the information above:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please keep your answer brief and concise, and focus on facts and data. (Again, only state what you see in the documents for \
sure and communicate if/in what way this may or may not relate to the question you need to answer! Use the answered \
sub-questions as well, but be cautious and reconsider the docments again for validation.)

Answer:
""".strip()

# sub_question_answer_str is empty
REFINED_ANSWER_PROMPT_WO_SUB_QUESTIONS = f"""
{{answered_sub_questions}}{{persona_specification}}

Use the information provided below - and only the provided information - to answer the provided question.

The information provided below consists of:
  1) an initial answer that was given but found to be lacking in some way.
  2) a number of documents that were also deemed relevant for the question.

It is critical that you provide proper inline citations to documents in the format [D1], [D2], [D3], etc! \
Please use format [D1][D2] and NOT [D1, D2] format if you cite two or more documents together! \
It is important that the citation is close to the information it supports. \
DO NOT just list all of the citations at the very end of your response. Citations are very important for the user!

{{history}}

{COMMON_RAG_RULES}
Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones, \
or assumptions you made.

Here is the contextual information:
{SEPARATOR_LINE_LONG}

*Initial Answer that was found to be lacking:
{SEPARATOR_LINE}
{{initial_answer}}
{SEPARATOR_LINE}

And here are relevant document information that support the sub-question answers, \
or that are relevant for the actual question:
{SEPARATOR_LINE}
{{relevant_docs}}
{SEPARATOR_LINE}

Lastly, here is the question I want you to answer based on the information above:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please keep your answer brief and concise, and focus on facts and data. (Again, only state what you see in the documents for \
sure and communicate if/in what way this may or may not relate to the question you need to answer!)

Answer:
""".strip()

REFINED_ANSWER_VALIDATION_PROMPT = f"""
{{persona_specification}}

Your task is to verify whether a given answer is truthful and accurate, and supported by the facts that you \
will be provided with.

The information provided below consists of:

  1) a question that needed to be answered

  2) a proposed answer to the question, whose accuracy you should assess

  3) potentially, a brief summary of the history of the conversation thus far, as it may give more context \
to the question. Note that the statements in the history are NOT considered as facts, ONLY but serve to to \
give context to the question.

  4) a number of answered sub-questions - you can take the answers as facts for these purposes.

  5) a number of relevant documents that should support the answer and that you should use as fact, \
i.e., if a statement in the document backs up a statement in the answer, then that statement in the answer \
should be considered as true.


IMPORTANT RULES AND CONSIDERATIONS:

 - Please consider the statements made in the proposed answer and assess whether they are truthful and accurate, based \
on the provided sub-answered and the documents. (Again, the history is NOT considered as facts!)

 - Look in particular for:
    * material statements that are not supported by the sub-answered or the documents
    * assignments and groupings that are not supported, like company A is competitor of company B, but this is not \
explicitly supported by documents or sub-answers, guesses or interpretations unless explicitly asked for

 - look also at the citations in the proposed answer and assess whether they are appropriate given the statements \
made in the proposed answer that cites the document.

 - Are items grouped together amongst one headline where not all items belong to the category of the headline? \
(Example: "Products used by Company A" where some products listed are not used by Company A)

 - Does the proposed answer address the question in full?

 - Is the answer specific to the question? Example: if the question asks for the prices for products by Company A, \
but the answer lists the prices for products by Company A and Company B, or products it cannot be sure are by \
Company A, then this is not quite specific enough to the question and the answer should be rejected.

- Similarly, if the question asks for properties of a certain class but the proposed answer lists or includes entities \
that are not of that class without very explicitly saying so, then the answer should be considered inaccurate.

 - If there are any calculations in the proposed answer that are not supported by the documents, they need to be tested. \
If any calculation is wrong, the proposed answer should be considered as not trustworthy.


Here is the information:
{SEPARATOR_LINE_LONG}

QUESTION:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

PROPOSED ANSWER:
{SEPARATOR_LINE}
{{proposed_answer}}
{SEPARATOR_LINE}

Here is the additional contextual information:
{SEPARATOR_LINE_LONG}

{{history}}

Sub-questions and their answers (to be considered as facts):
{SEPARATOR_LINE}
{{answered_sub_questions}}
{SEPARATOR_LINE}

And here are the relevant documents that support the sub-question answers, and that are relevant for the actual question:
{SEPARATOR_LINE}
{{relevant_docs}}
{SEPARATOR_LINE}


Please think through this step by step. Format your response just as a string in the following format:

Analysis: <think through your reasoning as outlined in the 'IMPORTANT RULES AND CONSIDERATIONS' section above, \
but keep it short. Come to a conclusion whether the proposed answer can be trusted>
Comments: <state your condensed comments you would give to a user reading the proposed answer, regarding the accuracy and \
specificity.>
{AGENT_ANSWER_SEPARATOR} <answer here only with yes or no, whether the proposed answer can be trusted. Base this on your \
analysis, but only say 'yes' (trustworthy) or 'no' (not trustworthy)>
""".strip()


INITIAL_REFINED_ANSWER_COMPARISON_PROMPT = f"""
For the given question, please compare the initial answer and the refined answer and determine if the refined answer is \
substantially better than the initial answer, not just a bit better. Better could mean:
 - additional information
 - more comprehensive information
 - more concise information
 - more structured information
 - more details
 - new bullet points
 - substantially more document citations ([D1], [D2], [D3], etc.)

Put yourself in the shoes of the user and think about whether the refined answer is really substantially better and \
delivers really new insights than the initial answer.

Here is the question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Here is the initial answer:
{SEPARATOR_LINE}
{{initial_answer}}
{SEPARATOR_LINE}

Here is the refined answer:
{SEPARATOR_LINE}
{{refined_answer}}
{SEPARATOR_LINE}

With these criteria in mind, is the refined answer substantially better than the initial answer?

Please answer with a simple "{YES}" or "{NO}"
""".strip()
