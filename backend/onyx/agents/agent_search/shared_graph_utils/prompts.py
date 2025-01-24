UNKNOWN_ANSWER = "I do not have enough information to answer this question."

NO_RECOVERED_DOCS = "No relevant documents recovered"

HISTORY_PROMPT = """\n
For more context, here is the history of the conversation so far that preceeded this question:
\n ------- \n
{history}
\n ------- \n\n
"""

REWRITE_PROMPT_MULTI_ORIGINAL = """ \n
    Please convert an initial user question into a 2-3 more appropriate short and pointed search queries for retrievel from a
    document store. Particularly, try to think about resolving ambiguities and make the search queries more specific,
    enabling the system to search more broadly.
    Also, try to make the search queries not redundant, i.e. not too similar! \n\n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n
    Formulate the queries separated by newlines (Do not say 'Query 1: ...', just write the querytext) as follows:
<query 1>
<query 2>
...
    queries: """

REWRITE_PROMPT_MULTI = """ \n
    Please create a list of 2-3 sample documents that could answer an original question. Each document
    should be about as long as the original question. \n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n
    Formulate the sample documents separated by '--' (Do not say 'Document 1: ...', just write the text): """

# The prompt is only used if there is no persona prompt, so the placeholder is ''
BASE_RAG_PROMPT = (
    """ \n
    {persona_specification}
    Use the context provided below - and only the
    provided context - to answer the given question. (Note that the answer is in service of anserwing a broader
    question, given below as 'motivation'.)

    Again, only use the provided context and do not use your internal knowledge! If you cannot answer the
    question based on the context, say """
    + f'"{UNKNOWN_ANSWER}"'
    + """. It is a matter of life and death that you do NOT
    use your internal knowledge, just the provided information!

    Make sure that you keep all relevant information, specifically as it concerns to the ultimate goal.
    (But keep other details as well.)

    \nContext:\n {context} \n

    Motivation:\n {original_question} \n\n
    \n\n
    And here is the question I want you to answer based on the context above (with the motivation in mind):
    \n--\n {question} \n--\n
    """
)

BASE_RAG_PROMPT_v2 = (
    """ \n
    Use the context provided below - and only the
    provided context - to answer the given question. (Note that the answer is in service of answering a broader
    question, given below as 'motivation'.)

    Again, only use the provided context and do not use your internal knowledge! If you cannot answer the
    question based on the context, say """
    + f'"{UNKNOWN_ANSWER}"'
    + """. It is a matter of life and death that you do NOT
    use your internal knowledge, just the provided information!

    Make sure that you keep all relevant information, specifically as it concerns to the ultimate goal.
    (But keep other details as well.)

    Please remember to provide inline citations in the format [[D1]](), [[D2]](), [[D3]](), etc.
    Proper citations are very important to the user!\n\n\n

    For your general information, here is the ultimate motivation:
    \n--\n {original_question} \n--\n
    \n\n
    And here is the actual question I want you to answer based on the context above (with the motivation in mind):
    \n--\n {question} \n--\n

    Here is the context:
    \n\n\n--\n {context} \n--\n
    """
)

SUB_CHECK_YES = "yes"
SUB_CHECK_NO = "no"

SUB_CHECK_PROMPT = (
    """
    Your task is to see whether a given answer addresses a given question.
    Please do not use any internal knowledge you may have - just focus on whether the answer
    as given seems to largely address the question as given, or at least addresses part of the question.
    Here is the question:
    \n ------- \n
    {question}
    \n ------- \n
    Here is the suggested answer:
    \n ------- \n
    {base_answer}
    \n ------- \n
    Does the suggested answer address the question? Please answer with """
    + f'"{SUB_CHECK_YES}" or "{SUB_CHECK_NO}".'
)


BASE_CHECK_PROMPT = """ \n
    Please check whether 1) the suggested answer seems to fully address the original question AND 2)the
    original question requests a simple, factual answer, and there are no ambiguities, judgements,
    aggregations, or any other complications that may require extra context. (I.e., if the question is
    somewhat addressed, but the answer would benefit from more context, then answer with 'no'.)

    Please only answer with 'yes' or 'no' \n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n
    Here is the proposed answer:
    \n ------- \n
    {initial_answer}
    \n ------- \n
    Please answer with yes or no:"""

VERIFIER_PROMPT = """
You are supposed to judge whether a document text contains data or information that is potentially relevant for a question.

Here is a document text that you can take as a fact:
--
DOCUMENT INFORMATION:
{document_content}
--

Do you think that this information is useful and relevant to answer the following question?
(Other documents may supply additional information, so do not worry if the provided information
is not enough to answer the question, but it needs to be relevant to the question.)
--
QUESTION:
{question}
--

Please answer with 'yes' or 'no':

Answer:

"""

INITIAL_DECOMPOSITION_PROMPT_BASIC = """ \n
If you think it is helpful, please decompose an initial user question into not more
than 4 appropriate sub-questions that help to answer the original question.
The purpose for this decomposition is to isolate individulal entities
(i.e., 'compare sales of company A and company B' -> 'what are sales for company A' + 'what are sales
for company B'), split ambiguous terms (i.e., 'what is our success with company A' -> 'what are our
sales with company A' + 'what is our market share with company A' + 'is company A a reference customer
 for us'), etc. Each sub-question should be realistically be answerable by a good RAG system.

Importantly, if you think it is not needed or helpful, please just return an empty list. That is ok too.

Here is the initial question:
\n ------- \n
{question}
\n ------- \n

Please formulate your answer as a list of subquestions:

Answer:
"""

REWRITE_PROMPT_SINGLE = """ \n
    Please convert an initial user question into a more appropriate search query for retrievel from a
    document store. \n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n

    Formulate the query: """

MODIFIED_RAG_PROMPT = (
    """You are an assistant for question-answering tasks. Use the context provided below
    - and only this context - to answer the question. It is a matter of life and death that you do NOT
    use your internal knowledge, just the provided information!
    If you don't have enough infortmation to generate an answer, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
    Use three sentences maximum and keep the answer concise.
    Pay also particular attention to the sub-questions and their answers, at least it may enrich the answer.
    Again, only use the provided context and do not use your internal knowledge!

    \nQuestion: {question}
    \nContext: {combined_context} \n

    Answer:"""
)

ORIG_DEEP_DECOMPOSE_PROMPT = """ \n
    An initial user question needs to be answered. An initial answer has been provided but it wasn't quite
    good enough. Also, some sub-questions had been answered and this information has been used to provide
    the initial answer. Some other subquestions may have been suggested based on little knowledge, but they
    were not directly answerable. Also, some entities, relationships and terms are givenm to you so that
    you have an idea of how the avaiolable data looks like.

    Your role is to generate 3-5 new sub-questions that would help to answer the initial question,
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
    - The sub-questions should be free from comparisions, ambiguities,judgements, aggregations, or any
    other complications that may require extra context.
    - The sub-questions MUST have the full context of the original question so that it can be executed by
    a RAG system independently without the original question available
      (Example:
        - initial question: "What is the capital of France?"
        - bad sub-question: "What is the name of the river there?"
        - good sub-question: "What is the name of the river that flows through Paris?"
    - For each sub-question, please provide a short explanation for why it is a good sub-question. So
    generate a list of dictionaries with the following format:
      [{{"sub_question": <sub-question>, "explanation": <explanation>, "search_term": <rewrite the
      sub-question using as a search phrase for the document store>}}, ...]

    \n\n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n

    Here is the initial sub-optimal answer:
    \n ------- \n
    {base_answer}
    \n ------- \n

    Here are the sub-questions that were answered:
    \n ------- \n
    {answered_sub_questions}
    \n ------- \n

    Here are the sub-questions that were suggested but not answered:
    \n ------- \n
    {failed_sub_questions}
    \n ------- \n

    And here are the entities, relationships and terms extracted from the context:
    \n ------- \n
    {entity_term_extraction_str}
    \n ------- \n

   Please generate the list of good, fully contextualized sub-questions that would help to address the
   main question. Again, please find questions that are NOT overlapping too much with the already answered
   sub-questions or those that already were suggested and failed.
   In other words - what can we try in addition to what has been tried so far?

   Please think through it step by step and then generate the list of json dictionaries with the following
   format:

   {{"sub_questions": [{{"sub_question": <sub-question>,
        "explanation": <explanation>,
        "search_term": <rewrite the sub-question using as a search phrase for the document store>}},
        ...]}} """

DEEP_DECOMPOSE_PROMPT = """ \n
    An initial user question needs to be answered. An initial answer has been provided but it wasn't quite
    good enough. Also, some sub-questions had been answered and this information has been used to provide
    the initial answer. Some other subquestions may have been suggested based on little knowledge, but they
    were not directly answerable. Also, some entities, relationships and terms are givenm to you so that
    you have an idea of how the avaiolable data looks like.

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
    - The sub-questions should be free from comparisions, ambiguities,judgements, aggregations, or any
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
    \n ------- \n
    {question}
    \n ------- \n
    {history}

    Here is the initial sub-optimal answer:
    \n ------- \n
    {base_answer}
    \n ------- \n

    Here are the sub-questions that were answered:
    \n ------- \n
    {answered_sub_questions}
    \n ------- \n

    Here are the sub-questions that were suggested but not answered:
    \n ------- \n
    {failed_sub_questions}
    \n ------- \n

    And here are the entities, relationships and terms extracted from the context:
    \n ------- \n
    {entity_term_extraction_str}
    \n ------- \n

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

DECOMPOSE_PROMPT = """ \n
    For an initial user question, please generate at 5-10 individual sub-questions whose answers would help
    \n to answer the initial question. The individual questions should be answerable by a good RAG system.
    So a good idea would be to \n use the sub-questions to resolve ambiguities and/or to separate the
    question for different entities that may be involved in the original question.

    In order to arrive at meaningful sub-questions, please also consider the context retrieved from the
    document store, expressed as entities, relationships and terms. You can also think about the types
    mentioned in brackets

    Guidelines:
    - The sub-questions should be specific to the question and provide richer context for the question,
    and or resolve ambiguities
    - Each sub-question - when answered - should be relevant for the answer to the original question
    - The sub-questions should be free from comparisions, ambiguities,judgements, aggregations, or any
    other complications that may require extra context.
    - The sub-questions MUST have the full context of the original question so that it can be executed by
    a RAG system independently without the original question available
      (Example:
        - initial question: "What is the capital of France?"
        - bad sub-question: "What is the name of the river there?"
        - good sub-question: "What is the name of the river that flows through Paris?"
    - For each sub-question, please provide a short explanation for why it is a good sub-question. So
    generate a list of dictionaries with the following format:
      [{{"sub_question": <sub-question>, "explanation": <explanation>}}, ...]

    \n\n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n

    And here are the entities, relationships and terms extracted from the context:
    \n ------- \n
    {entity_term_extraction_str}
    \n ------- \n

   Please generate the list of good, fully contextualized sub-questions that would help to address the
   main question. Don't be too specific unless the original question is specific.
   Please think through it step by step and then generate the list of json dictionaries with the following
   format:
   {{"sub_questions": [{{"sub_question": <sub-question>,
        "explanation": <explanation>,
        "search_term": <rewrite the sub-question using as a search phrase for the document store>}},
        ...]}} """

#### Consolidations
COMBINED_CONTEXT = """-------
    Below you will find useful information to answer the original question. First, you see a number of
    sub-questions with their answers. This information should be considered to be more focussed and
    somewhat more specific to the original question as it tries to contextualized facts.
    After that will see the documents that were considered to be relevant to answer the original question.

    Here are the sub-questions and their answers:
    \n\n {deep_answer_context} \n\n
    \n\n Here are the documents that were considered to be relevant to answer the original question:
    \n\n {formated_docs} \n\n
    ----------------
    """

SUB_QUESTION_EXPLANATION_RANKER_PROMPT = """-------
    Below you will find a question that we ultimately want to answer (the original question) and a list of
    motivations in arbitrary order for generated sub-questions that are supposed to help us answering the
    original question. The motivations are formatted as <motivation number>:  <motivation explanation>.
    (Again, the numbering is arbitrary and does not necessarily mean that 1 is the most relevant
    motivation and 2 is less relevant.)

    Please rank the motivations in order of relevance for answering the original question. Also, try to
    ensure that the top questions do not duplicate too much, i.e. that they are not too similar.
    Ultimately, create a list with the motivation numbers where the number of the most relevant
    motivations comes first.

    Here is the original question:
    \n\n {original_question} \n\n
    \n\n Here is the list of sub-question motivations:
    \n\n {sub_question_explanations} \n\n
    ----------------

    Please think step by step and then generate the ranked list of motivations.

    Please format your answer as a json object in the following format:
    {{"reasonning": <explain your reasoning for the ranking>,
      "ranked_motivations": <ranked list of motivation numbers>}}
    """


INITIAL_DECOMPOSITION_PROMPT_QUESTIONS = """
If you think it is helpful, please decompose an initial user question into no more than 3 appropriate sub-questions that help to
answer the original question. The purpose for this decomposition may be to
  1) isolate individual entities (i.e., 'compare sales of company A and company B' -> ['what are sales for company A',
     'what are sales for company B')]
  2) clarify or disambiguate ambiguous terms (i.e., 'what is our success with company A' -> ['what are our sales with company A',
      'what is our market share with company A', 'is company A a reference customer for us', etc.])
  3) if a term or a metric is essentially clear, but it could relate to various components of an entity and you are generally
    familiar with the entity, then you can decompose the question into sub-questions that are more specific to components
     (i.e., 'what do we do to improve scalability of product X', 'what do we to to improve scalability of product X',
     'what do we do to improve stability of product X', ...])
  4) research an area that could really help to answer the question. (But clarifications or disambiguations are more important.)

If you think that a decomposition is not needed or helpful, please just return an empty string. That is ok too.

Here is the initial question:
-------
{question}
-------
{history}

Please formulate your answer as a newline-separated list of questions like so:
 <sub-question>
 <sub-question>
 <sub-question>

Answer:"""

INITIAL_DECOMPOSITION_PROMPT_QUESTIONS_AFTER_SEARCH = """
If you think it is helpful, please decompose an initial user question into no more than 3 appropriate sub-questions that help to
answer the original question. The purpose for this decomposition may be to
  1) isolate individual entities (i.e., 'compare sales of company A and company B' -> ['what are sales for company A',
     'what are sales for company B')]
  2) clarify or disambiguate ambiguous terms (i.e., 'what is our success with company A' -> ['what are our sales with company A',
      'what is our market share with company A', 'is company A a reference customer for us', etc.])
  3) if a term or a metric is essentially clear, but it could relate to various components of an entity and you are generally
    familiar with the entity, then you can decompose the question into sub-questions that are more specific to components
     (i.e., 'what do we do to improve scalability of product X', 'what do we to to improve scalability of product X',
     'what do we do to improve stability of product X', ...])
  4) research an area that could really help to answer the question. (But clarifications or disambiguations are more important.)

Here are some other ruleds:

1) To give you some context, you will see below also some documents that relate to the question. Please only
use this information to learn what the question is approximately asking about, but do not focus on the details
to construct the sub-questions.
2) If you think that a decomposition is not needed or helpful, please just return an empty string. That is very muchok too.

Here are the sampple docs to give you some context:
-------
{sample_doc_str}
-------

And here is the initial question that you should think about decomposing:
-------
{question}
-------

{history}

Please formulate your answer as a newline-separated list of questions like so:
 <sub-question>
 <sub-question>
 <sub-question>

Answer:"""

INITIAL_DECOMPOSITION_PROMPT = """ \n
    Please decompose an initial user question into 2 or 3 appropriate sub-questions that help to
    answer the original question. The purpose for this decomposition is to isolate individulal entities
    (i.e., 'compare sales of company A and company B' -> 'what are sales for company A' + 'what are sales
    for company B'), split ambiguous terms (i.e., 'what is our success with company A' -> 'what are our
    sales with company A' + 'what is our market share with company A' + 'is company A a reference customer
    for us'), etc. Each sub-question should be realistically be answerable by a good RAG system. \n

    For each sub-question, please also create one search term that can be used to retrieve relevant
    documents from a document store.

    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n

    Please formulate your answer as a list of json objects with the following format:

   [{{"sub_question": <sub-question>, "search_term": <search term>}}, ...]

    Answer:
    """

INITIAL_RAG_BASE_PROMPT = (
    """ \n
You are an assistant for question-answering tasks. Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists ofa number of documents that were deemed relevant for the question.

IMPORTANT RULES:
- If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
You may give some additional facts you learned, but do not try to invent an answer.
- If the information is empty or irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
- If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Try to keep your answer concise.

Here is the contextual information from the document store:
\n ------- \n
{context} \n\n\n
\n ------- \n
And here is the question I want you to answer based on the context above (with the motivation in mind):
\n--\n {question} \n--\n
Answer:"""
)


AGENT_DECISION_PROMPT = """
You are an large language model assistant helping users address their information needs. You are tasked with deciding
whether to use a thorough agent search ('research') of a document store to answer a question or request, or whether you want to
address the question or request yourself as an LLM.

Here are some rules:
- If you think that a thorough search through a document store will help answer the question
or address the request, you should choose the 'research' option.
- If the question asks you do do somethng ('please create...', 'write for me...', etc.), you should choose the 'LLM' option.
- If you think the question is very general and does not refer to a contents of a document store, you should choose
the 'LLM' option.
- Otherwise, you should choose the 'research' option.
{history}

Here is the initial question:
-------
{question}
-------

Please decide whether to use the agent search or the LLM to answer the question. Choose from two choices,
'research' or 'LLM'.

Answer:"""

AGENT_DECISION_PROMPT_AFTER_SEARCH = """
You are an large language model assistant helping users address their information needs.  You are given an initial question
or request and very few sample of documents that a preliminary and fast search from a document store returned.
You are tasked with deciding whether to use a thorough agent search ('research') of the document store to answer a question
or request, or whether you want to address the question or request yourself as an LLM.

Here are some rules:
- If based on the retrieved documents you think there may be useful information in the document
store to answer or materially help with the request, you should choose the 'research' option.
- If you think that the retrieved document do not help to answer the question or do not help with the request, AND
you know the answer/can handle the request, you should choose the 'LLM' option.
- If the question asks you do do somethng ('please create...', 'write for me...', etc.), you should choose the 'LLM' option.
- If in doubt, choose the 'research' option.
{history}

Here is the initial question:
-------
{question}
-------

Here is the sample of documents that were retrieved from a document store:
-------
{sample_doc_str}
-------

Please decide whether to use the agent search ('research') or the LLM to answer the question. Choose from two choices,
'research' or 'LLM'.

Answer:"""

### ANSWER GENERATION PROMPTS

# Persona specification
ASSISTANT_SYSTEM_PROMPT_DEFAULT = """
You are an assistant for question-answering tasks."""

ASSISTANT_SYSTEM_PROMPT_PERSONA = """
You are an assistant for question-answering tasks. Here is more information about you:
\n ------- \n
{persona_prompt}
\n ------- \n
"""

SUB_QUESTION_ANSWER_TEMPLATE = """
    Sub-Question: Q{sub_question_nr}\n  Sub-Question:\n  - \n{sub_question}\n  --\nAnswer:\n  -\n {sub_answer}\n\n
    """

SUB_QUESTION_ANSWER_TEMPLATE_REVISED = """
    Sub-Question: Q{sub_question_nr}\n  Type: {level_type}\n Sub-Question:\n
- \n{sub_question}\n  --\nAnswer:\n  -\n {sub_answer}\n\n
    """

SUB_QUESTION_SEARCH_RESULTS_TEMPLATE = """
    Sub-Question: Q{sub_question_nr}\n  Sub-Question:\n  - \n{sub_question}\n  --\nRelevant Documents:\n
    -\n {formatted_sub_question_docs}\n\n
    """

INITIAL_RAG_PROMPT_SUB_QUESTION_SEARCH = (
    """ \n
{persona_specification}

Use the information provided below - and only the provided information - to answer the main question that will be provided.

The information provided below consists of:
    1) a number of sub-questions and supporting document information that would help answer them.
    2) a broader collection of documents that were deemed relevant for the question. These documents contain informattion
    that was also provided in the sub-questions and often more.

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
 - If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.
 - The answers to the subquestions should help you to structure your thoughts in order to answer the question.

Please provide inline citations of documentsin the format [[D1]](), [[D2]](), [[D3]](), etc.,  If you have multiple citations,
please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc. Feel free to cite documents in addition
to the sub-questions! Proper citations are important for the final answer to be verifiable! \n\n\n

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones,
or assumptions you made.

Here is the contextual information:
\n-------\n
*Answered Sub-questions (these should really help to organize your thoughts):
{answered_sub_questions}

And here are relevant document information that supports the sub-question answers, or that are relevant for the actual question:\n

{relevant_docs}

\n-------\n
\n
And here is the main question I want you to answer based on the information above:
\n--\n
{question}
\n--\n\n
Answer:"""
)


DIRECT_LLM_PROMPT = """ \n
{persona_specification}

Please answer the following question/address the request:
\n--\n
{question}
\n--\n\n
Answer:"""

INITIAL_RAG_PROMPT = (
    """ \n
{persona_specification}

Use the information provided below - and only the provided information - to answer the provided main question.

The information provided below consists of:
    1) a number of answered sub-questions - these are very important to help you organize your thoughts and your
answer
    2) a number of documents that deemed relevant for the question.

{history}

Please provide inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc.
Feel free to also cite sub-questions in addition to documents, but make sure that you have documents cited with the sub-question
citation. If you want to cite both a document and a sub-question, please use [[D1]]()[[Q3]](), or [[D2]]()[[D7]]()[[Q4]](), etc.
Again, please do not cite sub-questions without a document citation!
Citations are very important for the user!

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
\n-------\n
*Answered Sub-questions (these should really matter!):
{answered_sub_questions}

And here are relevant document information that support the sub-question answers, or that are relevant for the actual question:\n

{relevant_docs}

\n-------\n
\n
And here is the question I want you to answer based on the information above:
\n--\n
{question}
\n--\n\n
Answer:"""
)

# sub_question_answer_str is empty
INITIAL_RAG_PROMPT_NO_SUB_QUESTIONS = (
    """{answered_sub_questions}
{persona_specification}
Use the information provided below
- and only the provided information - to answer the provided question.
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

Please provide inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc. Citations are very important for the
user!

Try to keep your answer concise.

Here are is the relevant context information:
\n-------\n
{relevant_docs}
\n-------\n

And here is the question I want you to answer based on the context above
\n--\n
{question}
\n--\n

Answer:"""
)

REVISED_RAG_PROMPT = (
    """\n
{persona_specification}
Use the information provided below - and only the provided information - to answer the provided main question.

The information provided below consists of:
    1) an initial answer that was given but found to be lacking in some way.
    2) a number of answered sub-questions - these are very important(!) and definitely should help yoiu to answer
the main question. Note that the sub-questions have a type, 'initial' and 'revised'. The 'initial'
     ones were available for the initial answer, and the 'revised' were not. So please use the 'revised' sub-questions in
     particular to update/extend/correct the initial answer!
    3) a number of documents that were deemed relevant for the question. This the is the context that you use largey for
citations (see below).

Please provide inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc.
Feel free to also cite sub-questions in addition to documents, but make sure that you have documents cited with the sub-question
citation. If you want to cite both a document and a sub-question, please use [[D1]]()[[Q3]](), or [[D2]]()[[D7]]()[[Q4]](), etc.
Again, please do not cite sub-questions without a document citation!
Citations are very important for the user!\n\n

{history}

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say """
    + f'"{UNKNOWN_ANSWER}"'
    + """.
 - If the information is relevant but not fully conclusive, provide and answer to the extent you can but also
 specify that the information is not conclusive and why.
- Ignore any exisiting citations within the answered sub-questions, like [[D1]]()... and [[Q2]]()!
The citations you will need to use will need to refer to the documents (and sub-questions) that you are explicitly
presented with below!

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones,
or assumptions you made.

Here is the contextual information:
\n-------\n

*Initial Answer that was found to be lacking:
{initial_answer}

*Answered Sub-questions (these should really help ypu to research your answer! They also contain questions/answers
that were not available when the original answer was constructed):
{answered_sub_questions}

And here are the relevant documents that support the sub-question answers, and that are relevant for the actual question:\n

{relevant_docs}

\n-------\n
\n
Lastly, here is the main question I want you to answer based on the information above:
\n--\n
{question}
\n--\n\n
Answer:"""
)

# sub_question_answer_str is empty
REVISED_RAG_PROMPT_NO_SUB_QUESTIONS = (
    """{answered_sub_questions}\n
{persona_specification}
Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists of:
    1) an initial answer that was given but found to be lacking in some way.
    2) a number of documents that were also deemed relevant for the question.

Please provide inline citations to documents in the format [[D1]](), [[D2]](), [[D3]](), etc. If you have multiple
citations, please cite for example as [[D1]]()[[D3]](), or [[D2]]()[[D4]](), etc. Citations are very important for the user!\n\n

{history}

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
\n-------\n

*Initial Answer that was found to be lacking:
{initial_answer}

And here are relevant document information that support the sub-question answers, or that are relevant for the actual question:\n

{relevant_docs}

\n-------\n
\n
Lastly, here is the question I want you to answer based on the information above:
\n--\n
{question}
\n--\n\n
Answer:"""
)


ENTITY_TERM_PROMPT = """ \n
    Based on the original question and the context retieved from a dataset, please generate a list of
    entities (e.g. companies, organizations, industries, products, locations, etc.), terms and concepts
    (e.g. sales, revenue, etc.) that are relevant for the question, plus their relations to each other.

    \n\n
    Here is the original question:
    \n ------- \n
    {question}
    \n ------- \n
   And here is the context retrieved:
    \n ------- \n
    {context}
    \n ------- \n

    Please format your answer as a json object in the following format:

    {{"retrieved_entities_relationships": {{
        "entities": [{{
            "entity_name": <assign a name for the entity>,
            "entity_type": <specify a short type name for the entity, such as 'company', 'location',...>
        }}],
        "relationships": [{{
            "relationship_name": <assign a name for the relationship>,
            "relationship_type": <specify a short type name for the relationship, such as 'sales_to', 'is_location_of',...>,
            "relationship_entities": [<related entity name 1>, <related entity name 2>, ...]
        }}],
        "terms": [{{
            "term_name": <assign a name for the term>,
            "term_type": <specify a short type name for the term, such as 'revenue', 'market_share',...>,
            "term_similar_to": <list terms that are similar to this term>
        }}]
    }}
    }}
   """
