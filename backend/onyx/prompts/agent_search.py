# Standards
SEPARATOR_LINE = "-------"
UNKNOWN_ANSWER = "I do not have enough information to answer this question."
NO_RECOVERED_DOCS = "No relevant information recovered"
DATE_PROMPT = "Today is {date}.\n\n"
SUB_CHECK_YES = "yes"
SUB_CHECK_NO = "no"


# Framing/Support/Template Prompts
HISTORY_FRAMING_PROMPT = f"""
For more context, here is the history of the conversation so far that preceded this question:
{SEPARATOR_LINE}
{{history}}
{SEPARATOR_LINE}
""".strip()


ASSISTANT_SYSTEM_PROMPT_DEFAULT = (
    """You are an assistant for question-answering tasks."""
)

ASSISTANT_SYSTEM_PROMPT_PERSONA = f"""
You are an assistant for question-answering tasks. Here is more information about you:
{SEPARATOR_LINE}
{{persona_prompt}}
{SEPARATOR_LINE}
""".strip()


SUB_QUESTION_ANSWER_TEMPLATE = """\n
Sub-Question: Q{sub_question_num}\n  Sub-Question:\n  - \n{sub_question}\n  --\nAnswer:\n  -\n {sub_answer}\n\n
"""


SUB_QUESTION_ANSWER_TEMPLATE_REFINED = f"""
Sub-Question: Q{{sub_question_num}}\n
Type:
{SEPARATOR_LINE}
{{sub_question_type}}
{SEPARATOR_LINE}
Sub-Question:
{SEPARATOR_LINE}
{{sub_question}}
{SEPARATOR_LINE}
Answer:
{SEPARATOR_LINE}
{{sub_answer}}
{SEPARATOR_LINE}
""".strip()


SUB_QUESTION_ANSWER_TEMPLATE_REFINED = """\n
Sub-Question: Q{sub_question_num}\n  Type: {sub_question_type}\n Sub-Question:\n
- \n{sub_question}\n  --\nAnswer:\n  -\n {sub_answer}\n\n
    """


# Step/Utility Prompts
ENTITY_TERM_EXTRACTION_PROMPT = f"""
Based on the original question and some context retrieved from a dataset, please generate a list of
entities (e.g. companies, organizations, industries, products, locations, etc.), terms and concepts
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
{{
    "retrieved_entities_relationships": {{
        "entities": [
            {{
                "entity_name": "<assign a name for the entity>",
                "entity_type": "<specify a short type name for the entity, such as 'company', 'location',...>"
            }}
        ],
        "relationships": [
            {{
                "relationship_name": "<assign a name for the relationship>",
                "relationship_type": "<specify a short type name for the relationship, such as 'sales_to', 'is_location_of',...>",
                "relationship_entities": ["<related entity name 1>", "<related entity name 2>", "..."]
            }}
        ],
        "terms": [
            {{
                "term_name": "<assign a name for the term>",
                "term_type": "<specify a short type name for the term, such as 'revenue', 'market_share',...>",
                "term_similar_to": ["<list terms that are similar to this term>"]
            }}
        ]
    }}
}}
""".strip()


HISTORY_CONTEXT_SUMMARY_PROMPT = (
    "{persona_specification}\n\n"
    "Your task now is to summarize the key parts of the history of a conversation between a user and an agent."
    " The summary has two purposes:\n"
    "  1) providing the suitable context for a new question, and\n"
    "  2) To capture the key information that was discussed and that the user may have a follow-up question about.\n\n"
    "Here is the question:\n"
    f"{SEPARATOR_LINE}\n"
    "{question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "And here is the history:\n"
    f"{SEPARATOR_LINE}\n"
    "{history}\n"
    f"{SEPARATOR_LINE}\n\n"
    "Please provide a summarized context from the history so that the question makes sense and can"
    " - with suitable extra information - be answered.\n\n"
    "Do not use more than three or four sentences.\n\n"
    "History summary:"
).strip()


# INITIAL PHASE
# Sub-question
# Intentionally left a copy in case we want to modify this one differently
INITIAL_QUESTION_DECOMPOSITION_PROMPT = (
    "Decompose the initial user question into no more than 3 appropriate sub-questions that help to answer the"
    " original question. The purpose for this decomposition may be to:\n"
    "  1) isolate individual entities (i.e., 'compare sales of company A and company B' ->"
    " ['what are sales for company A', 'what are sales for company B'])\n"
    "  2) clarify or disambiguate ambiguous terms (i.e., 'what is our success with company A' ->"
    " ['what are our sales with company A','what is our market share with company A',"
    " 'is company A a reference customer for us', etc.])\n"
    "  3) if a term or a metric is essentially clear, but it could relate to various components of an entity and you"
    " are generally familiar with the entity, then you can decompose the question into sub-questions that are more"
    " specific to components (i.e., 'what do we do to improve scalability of product X', 'what do we to to improve"
    " scalability of product X', 'what do we do to improve stability of product X', ...])\n"
    "  4) research an area that could really help to answer the question.\n\n"
    "Here is the initial question to decompose:\n"
    f"{SEPARATOR_LINE}\n"
    "{question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "{history}\n\n"
    "Please formulate your answer as a newline-separated list of questions like so:\n"
    " <sub-question>\n"
    " <sub-question>\n"
    " <sub-question>\n"
    " ...\n\n"
    "Answer:"
).strip()


INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH = (
    "Decompose the initial user question into no more than 3 appropriate sub-questions that help to answer the"
    " original question. The purpose for this decomposition may be to:\n"
    "  1) isolate individual entities (i.e., 'compare sales of company A and company B' ->"
    " ['what are sales for company A', 'what are sales for company B'])\n"
    "  2) clarify or disambiguate ambiguous terms (i.e., 'what is our success with company A' ->"
    " ['what are our sales with company A','what is our market share with company A',"
    " 'is company A a reference customer for us', etc.])\n"
    "  3) if a term or a metric is essentially clear, but it could relate to various components of an entity and you"
    " are generally familiar with the entity, then you can decompose the question into sub-questions that are more"
    " specific to components (i.e., 'what do we do to improve scalability of product X', 'what do we to to improve"
    " scalability of product X', 'what do we do to improve stability of product X', ...])\n"
    "  4) research an area that could really help to answer the question.\n\n"
    "To give you some context, you will see below also some documents that may relate to the question. Please only"
    " use this information to learn what the question is approximately asking about, but do not focus on the details"
    " to construct the sub-questions! Also, some of the entities, relationships and terms that are in the dataset may"
    " not be in these few documents, so DO NOT focussed too much on the documents when constructing the sub-questions!"
    " Decomposition and disambiguations are most important!\n\n"
    "Here are the sample docs to give you some context:\n"
    f"{SEPARATOR_LINE}\n"
    "{sample_doc_str}\n"
    f"{SEPARATOR_LINE}\n\n"
    "And here is the initial question to decompose:\n"
    f"{SEPARATOR_LINE}\n"
    "{question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "{history}\n\n"
    "Please formulate your answer as a newline-separated list of questions like so:\n"
    " <sub-question>\n"
    " <sub-question>\n"
    " <sub-question>\n"
    " ...\n\n"
    "Answer:"
).strip()


# Retrieval
QUERY_REWRITING_PROMPT = (
    "Please convert the initial user question into a 2-3 more appropriate short and pointed search queries for"
    " retrieval from a document store. Particularly, try to think about resolving ambiguities and make the search"
    " queries more specific, enabling the system to search more broadly.\n"
    "Also, try to make the search queries not redundant, i.e. not too similar!\n\n"
    "Here is the initial question:\n"
    f"{SEPARATOR_LINE}\n"
    "{question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "Formulate the queries separated by newlines (Do not say 'Query 1: ...', just write the querytext) as follows:\n"
    "<query 1>\n"
    "<query 2>\n"
    "...\n\n"
    "Queries:"
)


DOCUMENT_VERIFICATION_PROMPT = (
    "Determine whether the following document text contains data or information that is potentially relevant "
    "for a question. It does not have to be fully relevant, but check whether it has some information that "
    "would help - possibly in conjunction with other documents - to address the question.\n\n"
    "Be careful that you do not use a document where you are not sure whether the text applies to the objects "
    "or entities that are relevant for the question. For example, a book about chess could have long passage "
    "discussing the psychology of chess without - within the passage - mentioning chess. If now a question "
    "is asked about the psychology of football, one could be tempted to use the document as it does discuss "
    "psychology in sports. However, it is NOT about football and should not be deemed relevant. Please "
    "consider this logic.\n\n"
    "DOCUMENT TEXT:\n"
    f"{SEPARATOR_LINE}\n"
    "{document_content}\n"
    f"{SEPARATOR_LINE}\n\n"
    "Do you think that this document text is useful and relevant to answer the following question?\n\n"
    "QUESTION:\n"
    f"{SEPARATOR_LINE}\n"
    "{question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "Please answer with exactly and only a 'yes' or 'no':\n\n"
    "Answer:"
).strip()


# Sub-Question Anser Generation
SUB_QUESTION_RAG_PROMPT = (
    "Use the context provided below - and only the provided context - to answer the given question. "
    "(Note that the answer is in service of answering a broader question, given below as 'motivation'.)\n\n"
    "Again, only use the provided context and do not use your internal knowledge! If you cannot answer the "
    f'question based on the context, say "{UNKNOWN_ANSWER}". It is a matter of life and death that you do NOT '
    "use your internal knowledge, just the provided information!\n\n"
    "Make sure that you keep all relevant information, specifically as it concerns to the ultimate goal. "
    "(But keep other details as well.)\n\n"
    "It is critical that you provide inline citations in the format [[D1]](), [[D2]](), [[D3]](), etc! "
    "It is important that the citation is close to the information it supports. "
    "Proper citations are very important to the user!\n\n"
    "For your general information, here is the ultimate motivation:\n"
    f"{SEPARATOR_LINE}\n"
    "{original_question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "And here is the actual question I want you to answer based on the context above (with the motivation in mind):\n"
    f"{SEPARATOR_LINE}\n"
    "{question}\n"
    f"{SEPARATOR_LINE}\n\n"
    "Here is the context:\n"
    f"{SEPARATOR_LINE}\n"
    "{context}\n"
    f"{SEPARATOR_LINE}\n\n"
    "Please keep your answer brief and concise, and focus on facts and data.\n\n"
    "Answer:"
).strip()


SUB_ANSWER_CHECK_PROMPT = (
    """\n
Your task is to see whether a given answer addresses a given question.
Please do not use any internal knowledge you may have - just focus on whether the answer
as given seems to largely address the question as given, or at least addresses part of the question.
Here is the question:
\n-------\n
{question}
\n-------\n
Here is the suggested answer:
\n-------\n
{base_answer}
\n-------\n
Does the suggested answer address the question? Please answer with """
    + f'"{SUB_CHECK_YES}" or "{SUB_CHECK_NO}".'
)


# Initial Answer Generation
INITIAL_ANSWER_PROMPT_W_SUB_QUESTIONS = (
    """ \n
{persona_specification}
 {date_prompt}
Use the information provided below - and only the provided information - to answer the provided main question.

The information provided below consists of:
    1) a number of answered sub-questions - these are very important to help you organize your thoughts and your answer
    2) a number of documents that deemed relevant for the question.

{history}

It is critical that you provide prover inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc.!
It is important that the citation is close to the information it supports. If you have multiple citations that support
a fact, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc.
Feel free to also cite sub-questions in addition to documents, but make sure that you have documents cited with the sub-question
citation. If you want to cite both a document and a sub-question, please use [[D1]]()[[Q3]](), or [[D2]]()[[D7]]()[[Q4]](), etc.
Again, please NEVER cite sub-questions without a document citation!
Proper citations are very important for the user!

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
 - If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones,
or assumptions you made.

Here is the contextual information:
---------------

*Answered Sub-questions (these should really matter!):
\n-------\n
{answered_sub_questions}
\n-------\n

And here are relevant document information that support the sub-question answers, or that are relevant for the actual question:\n
\n-------\n
{relevant_docs}
\n-------\n

And here is the question I want you to answer based on the information above:
\n-------\n
{question}
\n-------\n\n

Please keep your answer brief and concise, and focus on facts and data.

Answer:"""
)


# used if sub_question_answer_str is empty
INITIAL_ANSWER_PROMPT_WO_SUB_QUESTIONS = (
    """\n
{answered_sub_questions}
{persona_specification}
{date_prompt}

Use the information provided below - and only the provided information - to answer the provided question.
The information provided below consists of a number of documents that were deemed relevant for the question.
{history}

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some  additional facts you learned, but do not try to invent an answer.
 - If the information is irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
 - If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Again, you should be sure that the answer is supported by the information provided!

It is critical that you provide proper inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc!
It is important that the citation is close to the information it supports. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc. Citations are very important for the
user!

Try to keep your answer concise.

Here are is the relevant context information:
\n-------\n
{relevant_docs}
\n-------\n

And here is the question I want you to answer based on the context above
\n-------\n
{question}
\n-------\n

Please keep your answer brief and concise, and focus on facts and data.

Answer:"""
)

# REFINEMENT PHASE

REFINEMENT_QUESTION_DECOMPOSITION_PROMPT = """ \n
An initial user question needs to be answered. An initial answer has been provided but it wasn't quite
good enough. Also, some sub-questions had been answered and this information has been used to provide
the initial answer. Some other subquestions may have been suggested based on little knowledge, but they
were not directly answerable. Also, some entities, relationships and terms are given to you so that
you have an idea of how the available data looks like.

Your role is to generate 2-4 new sub-questions that would help to answer the initial question,
considering:

1) The initial question
2) The initial answer that was found to be unsatisfactory
3) The sub-questions that were answered
4) The sub-questions that were suggested but not answered
5) The entities, relationships and terms that were extracted from the context

The individual questions should be answerable by a good RAG system.
So a good idea would be to use the sub-questions to resolve ambiguities and/or to separate the
question for different entities that may be involved in the original question, but in a way that does
not duplicate questions that were already tried.

Additional Guidelines:
- The sub-questions should be specific to the question and provide richer context for the question,
resolve ambiguities, or address shortcoming of the initial answer
- Each sub-question - when answered - should be relevant for the answer to the original question
- The sub-questions should be free from comparisons, ambiguities,judgements, aggregations, or any
other complications that may require extra context.
- The sub-questions MUST have the full context of the original question so that it can be executed by
a RAG system independently without the original question available
    (Example:
    - initial question: "What is the capital of France?"
    - bad sub-question: "What is the name of the river there?"
    - good sub-question: "What is the name of the river that flows through Paris?"
- For each sub-question, please also provide a search term that can be used to retrieve relevant
documents from a document store.
- Consider specifically the sub-questions that were suggested but not answered. This is a sign that they are not
answerable with the available context, and you should not ask similar questions.
\n\n
Here is the initial question:
\n-------\n
{question}
\n-------\n
{history}

Here is the initial sub-optimal answer:
\n-------\n
{base_answer}
\n-------\n

Here are the sub-questions that were answered:
\n-------\n
{answered_sub_questions}
\n-------\n

Here are the sub-questions that were suggested but not answered:
\n-------\n
{failed_sub_questions}
\n-------\n

And here are the entities, relationships and terms extracted from the context:
\n-------\n
{entity_term_extraction_str}
\n-------\n

Please generate the list of good, fully contextualized sub-questions that would help to address the
main question.

Specifically pay attention also to the entities, relationships and terms extracted, as these indicate what type of
objects/relationships/terms you can ask about! Do not ask about entities, terms or relationships that are not
mentioned in the 'entities, relationships and terms' section.

Again, please find questions that are NOT overlapping too much with the already answered
sub-questions or those that already were suggested and failed.
In other words - what can we try in addition to what has been tried so far?

Generate the list of questions separated by one new line like this:
<sub-question 1>
<sub-question 2>
<sub-question 3>
...
   """


REFINED_ANSWER_PROMPT_W_SUB_QUESTIONS = (
    """\n
{persona_specification}
{date_prompt}
Your task is to improve on a given answer to a question, as the initial answer was found to be lacking in some way.

Use the information provided below - and only the provided information - to write your new and improved answer.

The information provided below consists of:
    1) an initial answer that was given but found to be lacking in some way.
    2) a number of answered sub-questions - these are very important(!) and definitely should help you to answer
the main question. Note that the sub-questions have a type, 'initial' and 'refined'. The 'initial'
ones were available for the creation of the initial answer, but the 'refined' were not, they are new. So please use
the 'refined' sub-questions in particular to update/extend/correct/enrich the initial answer and to add
more details/new facts!

    3) a number of documents that were deemed relevant for the question. This the is the context that you use largely for
citations (see below). So consider the answers to the sub-questions as guidelines to construct your new answer, but
make sure you cite the relevant document for a fact!

It is critical that you provide proper inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc!
It is important that the citation is close to the information it supports. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc.
Feel free to also cite sub-questions in addition to documents, but make sure that you have documents cited with the sub-question
citation. If you want to cite both a document and a sub-question, please use [[D1]]()[[Q3]](), or [[D2]]()[[D7]]()[[Q4]](), etc.
Again, please NEVER cite sub-questions without a document citation!
Proper citations are very important for the user!\n\n

{history}

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
 - If the information is relevant but not fully conclusive, provide an answer to the extent you can but also
 specify that the information is not conclusive and why.
- Ignore any existing citations within the answered sub-questions, like [[D1]]()... and [[Q2]]()!
The citations you will need to use will need to refer to the documents (and sub-questions) that you are explicitly
presented with below!

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones,
or assumptions you made.

Here is the contextual information:
---------------

*Initial Answer that was found to be lacking:
\n-------\n
{initial_answer}
\n-------\n

*Answered Sub-questions (these should really help you to research your answer! They also contain questions/answers
that were not available when the original answer was constructed):
{answered_sub_questions}

And here are the relevant documents that support the sub-question answers, and that are relevant for the actual question:\n
\n-------\n
{relevant_docs}
\n-------\n

\n
Lastly, here is the main question I want you to answer based on the information above:
\n-------\n
{question}
\n-------\n

Please keep your answer brief and concise, and focus on facts and data.

Answer:"""
)

# sub_question_answer_str is empty
REFINED_ANSWER_PROMPT_WO_SUB_QUESTIONS = (
    """\n
{answered_sub_questions}\n
{persona_specification}
{date_prompt}
Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists of:
    1) an initial answer that was given but found to be lacking in some way.
    2) a number of documents that were also deemed relevant for the question.

It is critical that you provide proper] inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc!
 It is important that the citation is close to the information it supports. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc. Citations are very important for the user!\n\n
\n-------\n
{history}
\n-------\n
IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
 - If the information is relevant but not fully conclusive, provide and answer to the extent you can but also
 specify that the information is not conclusive and why.

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones,
or assumptions you made.

Here is the contextual information:
---------------

*Initial Answer that was found to be lacking:
\n-------\n
{initial_answer}
\n-------\n

And here are relevant document information that support the sub-question answers, or that are relevant for the actual question:\n
\n-------\n
{relevant_docs}
\n-------\n
\n
Lastly, here is the question I want you to answer based on the information above:
\n-------\n
{question}
\n-------\n\n
Please keep your answer brief and concise, and focus on facts and data.

Answer:"""
)


INITIAL_REFINED_ANSWER_COMPARISON_PROMPT = """
For the given question, please compare the initial answer and the refined answer and determine if
the refined answer is substantially better than the initial answer, not just a bit better. Better could mean:
 - additional information
 - more comprehensive information
 - more concise information
 - more structured information
 - morde details
 - new bullet points
 - substantially more document citations ([[D1]](), [[D2]](), [[D3]](), etc.)

 Put yourself in the shoes of the user and think about whether the refined answer is really substantially
 better and delivers really new insights than the initial answer.

Here is the question:
\n-------\n
{question}
\n-------\n

Here is the initial answer:
\n-------\n
{initial_answer}
\n-------\n

Here is the refined answer:
\n-------\n
{refined_answer}
\n-------\n

With these criteria in mind, is the refined answer substantially better than the initial answer?

Please answer with a simple 'yes' or 'no'.
"""
