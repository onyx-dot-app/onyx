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
BASE_RAG_PROMPT = """ \n
    {persona_specification}
    Use the context provided below - and only the
    provided context - to answer the given question. (Note that the answer is in service of anserwing a broader
    question, given below as 'motivation'.)

    Again, only use the provided context and do not use your internal knowledge! If you cannot answer the
    question based on the context, say "I don't know". It is a matter of life and death that you do NOT
    use your internal knowledge, just the provided information!

    Make sure that you keep all relevant information, specifically as it concerns to the ultimate goal.
    (But keep other details as well.)

    \nContext:\n {context} \n

    Motivation:\n {original_question} \n\n
    \n\n
    And here is the question I want you to answer based on the context above (with the motivation in mind):
    \n--\n {question} \n--\n
    """

BASE_RAG_PROMPT_v2 = """ \n
    Use the context provided below - and only the
    provided context - to answer the given question. (Note that the answer is in service of answering a broader
    question, given below as 'motivation'.)

    Again, only use the provided context and do not use your internal knowledge! If you cannot answer the
    question based on the context, say "I don't know". It is a matter of life and death that you do NOT
    use your internal knowledge, just the provided information!

    Make sure that you keep all relevant information, specifically as it concerns to the ultimate goal.
    (But keep other details as well.)

    Please remember to provide inline citations in the format [D1], [D2], [D3], etc.\n\n\n

    For your general information, here is the ultimate motivation:
    \n--\n {original_question} \n--\n
    \n\n
    And here is the actual question I want you to answer based on the context above (with the motivation in mind):
    \n--\n {question} \n--\n

    Here is the context:
    \n\n\n--\n {context} \n--\n
    """


SUB_CHECK_PROMPT = """
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
    Does the suggested answer address the question? Please answer with yes or no:"""


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

MODIFIED_RAG_PROMPT = """You are an assistant for question-answering tasks. Use the context provided below
    - and only this context - to answer the question. If you don't know the answer, just say "I don't know".
    Use three sentences maximum and keep the answer concise.
    Pay also particular attention to the sub-questions and their answers, at least it may enrich the answer.
    Again, only use the provided context and do not use your internal knowledge! If you cannot answer the
    question based on the context, say "I don't know". It is a matter of life and death that you do NOT
    use your internal knowledge, just the provided information!

    \nQuestion: {question}
    \nContext: {combined_context} \n

    Answer:"""

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
    - For each sub-question, please also provide a search term that can be used to retrieve relevant
    documents from a document store.
    - Consider specifically the sub-questions that were suggested but not answered. This is a sign that they are not
    answerable with the available context, and you should not ask similar questions.
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
If you think it is helpful, please decompose an initial user question into 2 or 4 appropriate sub-questions that help to
answer the original question. The purpose for this decomposition is to
  1) isolate individual entities (i.e., 'compare sales of company A and company B' -> ['what are sales for company A',
     'what are sales for company B')]
  2) clarify or disambiguate ambiguous terms (i.e., 'what is our success with company A' -> ['what are our sales with company A',
      'what is our market share with company A', 'is company A a reference customer for us', etc.])
  3) if a term or a metric is essentially clear, but it could relate to various components of an entity and you are generally
    familiar with the entity, then you can decompose the question into sub-questions that are more specific to components
     (i.e., 'what do we do to improve scalability of product X', 'what do we to to improve scalability of product X',
     'what do we do to improve stability of product X', ...])

If you think that a decomposition is not needed or helpful, please just return an empty string. That is ok too.

Here is the initial question:
-------
{question}
-------
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

INITIAL_RAG_BASE_PROMPT = """ \n
You are an assistant for question-answering tasks. Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists ofa number of documents that were deemed relevant for the question.

IMPORTANT RULES:
- If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
You may give some additional facts you learned, but do not try to invent an answer.
- If the information is empty or irrelevant, just say "I don't know".
- If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Try to keep your answer concise.

Here is the contextual information from the document store:
\n ------- \n
{context} \n\n\n
\n ------- \n
And here is the question I want you to answer based on the context above (with the motivation in mind):
\n--\n {question} \n--\n
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

SUB_QUESTION_SEARCH_RESULTS_TEMPLATE = """
    Sub-Question: Q{sub_question_nr}\n  Sub-Question:\n  - \n{sub_question}\n  --\nRelevant Documents:\n
    -\n {formatted_sub_question_docs}\n\n
    """

INITIAL_RAG_PROMPT_SUB_QUESTION_SEARCH = """ \n
{persona_specification}

Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists of:
    1) a number of sub-questions and supporting document information that would help answer them.
    2) a broader collection of documents that were deemed relevant for the question. These documents contain informattion
    that was also provided in the sub-questions and often more.

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say "I don't know".
 - If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Please provide inline citations of documentsin the format [D1], [D2], [D3], etc.,  If you have multiple citations,
please cite for example as [D1][Q3], or [D2][D4], etc. Feel free to cite documents in addition to the sub-questions!
Proper citations are important for the final answer to be verifiable! \n\n\n

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


INITIAL_RAG_PROMPT = """ \n
{persona_specification}

Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists of:
    1) a number of answered sub-questions - these are very important(!) and definitely should be
    considered to answer the question.
    2) a number of documents that were also deemed relevant for the question.

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say "I don't know".
 - If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Remember to provide inline citations of documentsin the format [D1], [D2], [D3], etc., and  [Q1], [Q2],... if
you want to cite the answer to a sub-question. If you have multiple citations, please cite for example
as [D1][Q3], or [D2][D4], etc. Feel free to cite documents in addition to the sub-questions!
Proper citations are important for the final answer to be verifiable! \n\n\n

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

# sub_question_answer_str is empty
INITIAL_RAG_PROMPT_NO_SUB_QUESTIONS = """{answered_sub_questions}
{persona_specification}
Use the information provided below
- and only the provided information - to answer the provided question.
The information provided below consists of a number of documents that were deemed relevant for the question.

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some  additional facts you learned, but do not try to invent an answer.
 - If the information is irrelevant, just say "I don't know".
 - If the information is relevant but not fully conclusive, specify that the information is not conclusive and say why.

Again, you should be sure that the answer is supported by the information provided!

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

REVISED_RAG_PROMPT = """\n
{persona_specification}
Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists of:
    1) an initial answer that was given but found to be lacking in some way.
    2) a number of answered sub-questions - these are very important(!) and definitely should be
    considered to answer the question.
    3) a number of documents that were also deemed relevant for the question.

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say "I don't know".
 - If the information is relevant but not fully conclusive, provide and answer to the extent you can but also
 specify that the information is not conclusive and why.

Again, you should be sure that the answer is supported by the information provided!

Try to keep your answer concise. But also highlight uncertainties you may have should there be substantial ones,
or assumptions you made.

Here is the contextual information:
\n-------\n

*Initial Answer that was found to be lacking:
{initial_answer}

*Answered Sub-questions (these should really matter! They also contain questions/answers that were not available when the original
answer was constructed):
{answered_sub_questions}

And here are relevant document information that support the sub-question answers, or that are relevant for the actual question:\n

{relevant_docs}

\n-------\n
\n
Lastly, here is the question I want you to answer based on the information above:
\n--\n
{question}
\n--\n\n
Answer:"""

# sub_question_answer_str is empty
REVISED_RAG_PROMPT_NO_SUB_QUESTIONS = """{sub_question_answer_str}\n
{persona_specification}
Use the information provided below - and only the
provided information - to answer the provided question.

The information provided below consists of:
    1) an initial answer that was given but found to be lacking in some way.
    2) a number of documents that were also deemed relevant for the question.

IMPORTANT RULES:
 - If you cannot reliably answer the question solely using the provided information, say that you cannot reliably answer.
 You may give some additional facts you learned, but do not try to invent an answer.
 - If the information is empty or irrelevant, just say "I don't know".
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
