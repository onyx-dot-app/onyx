from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.models import DRTimeBudget
from onyx.agents.agent_search.dr.states import DRPath


# Standards
SEPARATOR_LINE = "-------"
SEPARATOR_LINE_LONG = "---------------"
NO_EXTRACTION = "No extraction of knowledge graph objects was feasible."
YES = "yes"
NO = "no"

KNOWLEDGE_GRAPH = DRPath.KNOWLEDGE_GRAPH.value
SEARCH = DRPath.SEARCH.value
CLOSER = DRPath.CLOSER.value
INTERNET_SEARCH = DRPath.INTERNET_SEARCH.value


DONE_STANDARD: dict[str, str] = {}

BASIC_SEARCH_PROMPTS: dict[str, str] = {}

DONE_STANDARD[DRTimeBudget.FAST] = (
    "Try to make sure that you think you have enough information to \
answer the question in the spirit and the level of detail that is pretty explicit in the question."
)

DONE_STANDARD[DRTimeBudget.DEEP] = (
    "Try to make sure that you think you have enough information to \
answer the question in the spirit and the level of detail that is pretty explicit in the question. \
Be particularly sensitive to details that you think the user would be interested in. Consider \
asking follow-up questions as necessary."
)


# TODO: restructure this so each tool is a class with a description, and agents can select which tools to use
TOOL_DESCRIPTION: dict[str, str] = {}
TOOL_DESCRIPTION[
    SEARCH
] = f"""\
- The "{SEARCH}" tool is used to answer questions that can be answered using the information \
present in the connected documents.
Note that the search tool is not well suited for time-ordered questions (e.g., '...latest email...', \
'...last 2 jiras resolved...') and answering aggregation-type questions (e.g., 'how many...') \
(unless that info is present in the connected documents). If there are better suited tools \
for answering those questions, use them instead.
You generally should not need to ask clarification questions about the topics being searched for \
by the {SEARCH} tool, as the retrieved documents will likely provide you with more context.
The {SEARCH} tool DOES support parallel calls of up to {MAX_DR_PARALLEL_SEARCH} queries.
"""

TOOL_DESCRIPTION[
    INTERNET_SEARCH
] = f"""\
- The "{INTERNET_SEARCH}" tool is used to answer questions that can be answered using the information \
that is public on the internet. In case the {SEARCH} and/or {KNOWLEDGE_GRAPH} tools are also available \
you should think about whether the data is likely private data (in which case the {SEARCH} and/or \
{KNOWLEDGE_GRAPH} tools should be used), or likely public data (in which case the {INTERNET_SEARCH} tool \
should be used). If in doubt you should consider the data to be private and you should not user the \
{INTERNET_SEARCH} tool.
Note also that if an earlier call was sent to the {SEARCH} tool, and the request was essentially not answered, \
then you should consider sending a new request to the {INTERNET_SEARCH} tool and vice versa!
The {INTERNET_SEARCH} tool DOES support parallel calls of up to {MAX_DR_PARALLEL_SEARCH} queries.
"""

TOOL_DESCRIPTION[
    KNOWLEDGE_GRAPH
] = f"""\
- The "{KNOWLEDGE_GRAPH}" tool is similar to a search tool but it answers questions based on \
entities and relationships extracted from the source documents. \
It is suitable for answering complex questions about specific entities and relationships, such as \
"summarize the open tickets assigned to John in the last month". \
It can also query a relational database containing the entities and relationships, allowing it to \
answer aggregation-type questions like 'how many jiras did each employee close last month?'. \
However, the {KNOWLEDGE_GRAPH} tool MUST ONLY BE USED if the question can be answered with the \
entity/relationship types that are available in the knowledge graph.
Note that the {KNOWLEDGE_GRAPH} tool can both FIND AND ANALYZE/AGGREGATE/QUERY the relevant documents/entities. \
E.g., if the question is "how many open jiras are there", you should pass that as a single query to the \
{KNOWLEDGE_GRAPH} tool, instead of splitting it into finding and counting the open jiras.
Note also that the {KNOWLEDGE_GRAPH} tool is slower than the standard search tools.
Importantly, the {KNOWLEDGE_GRAPH} tool can also analyze the relevant documents/entities, so DO NOT \
try to first find documents and then analyze them in a future iteration. Query the {KNOWLEDGE_GRAPH} \
tool directly, like 'summarize the most recent jira created by John'.
Lastly, to use the {KNOWLEDGE_GRAPH} tool, it is important that you know the specific entity/relation type being \
referred to in the question. If it cannot reasonably be inferred, consider asking a clarification question.
On the other hand, the {KNOWLEDGE_GRAPH} tool does NOT require attributes to be specified. I.e., it is possible \
to search for entities without narrowing down specific attributes. Thus, if the question asks for an entity or \
an entity type in general, you should not ask clarification questions to specify the attributes.
"""

TOOL_DESCRIPTION[
    CLOSER
] = f"""\
- The "{CLOSER}" tool does not directly have access to the documents, but will use the results from \
previous tool calls to generate a comprehensive final answer. It should always be called exactly once \
at the very end to consolidate the gathered information, run any comparisons if needed, and pick out \
the most relevant information to answer the question. You can also skip straight to the {CLOSER} \
if there is sufficient information in the provided history to answer the question.
"""

TOOL_DIFFERENTIATION_HINTS: dict[str, dict[str, str]] = {
    DRPath.SEARCH.value: {
        DRPath.INTERNET_SEARCH.value: f"""\
  - in general, you should use the {SEARCH} tool first, and only use the {INTERNET_SEARCH} tool if the \
{SEARCH} tool result did not contain the information you need, or the user specifically asks or implies \
the use of the {INTERNET_SEARCH} tool. Moreover, if the {INTERNET_SEARCH} tool result did not contain the \
information you need, you can switch to the {SEARCH} tool the following iteration.
"""
    },
    DRPath.KNOWLEDGE_GRAPH.value: {
        DRPath.SEARCH.value: f"""\
    - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard {SEARCH} query should be used or a \
{KNOWLEDGE_GRAPH} query. For example, 'use a simple search to find <xyz>' would refer to a standard {SEARCH} query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a {KNOWLEDGE_GRAPH} query.
"""
    },
}


TOOL_QUESTION_HINTS: dict[str, str] = {
    DRPath.SEARCH.value: f"""if the tool is {SEARCH}, the question should be \
written as a list of suitable searches of up to {MAX_DR_PARALLEL_SEARCH} queries. \
If searching for multiple \
aspects is required you should split the question into multiple sub-questions.
""",
    DRPath.INTERNET_SEARCH.value: f"""if the tool is {INTERNET_SEARCH}, the question should be \
written as a list of suitable searches of up to {MAX_DR_PARALLEL_SEARCH} queries. So the \
searches should be rather short and focus on one specific aspect. If searching for multiple \
aspects is required you should split the question into multiple sub-questions.
""",
    DRPath.KNOWLEDGE_GRAPH.value: f"""if the tool is {KNOWLEDGE_GRAPH}, the question should be \
written as a list of one question.
""",
    DRPath.CLOSER.value: f"""if the tool is {CLOSER}, the list of questions should simply be \
['Answer the original question with the information you have.'].
""",
}


KG_TYPES_DESCRIPTIONS = f"""\
Here are the entity types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_entities---
{SEPARATOR_LINE}

Here are the relationship types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_relationships---
{SEPARATOR_LINE}
"""

ORCHESTRATOR_DEEP_INITIAL_PLAN_PROMPT = f"""
You are a great Assistant that is an expert at analyzing a question and breaking it up into a \
series of high-level, answerable sub-questions.

Given the user query and the list of available tools, your task is to devise a high-level plan \
consisting of a list of the iterations, each iteration consisting of the \
aspects to investigate, so that by the end of the process you have gathered sufficient \
information to generate a well-researched and highly relevant answer to the user query.

Note that the plan will only be used as a guideline, and a separate agent will use your plan along \
with the results from previous iterations to generate the specific questions to send to the tool for each \
iteration. Thus you should not be too specific in your plan as some steps could be dependent on \
previous steps.

Assume that all steps will be executed sequentially, so the answers of earlier steps will be known \
at later steps. To capture that, you can refer to earlier results in later steps. (Example of a 'later'\
question: 'find information for each result of step 3.')

You have these ---num_available_tools--- tools available, \
---available_tools---.

---tool_descriptions---

---kg_types_descriptions---

Here is the question that you must device a plan for answering:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

Finally, here are the past few chat messages for reference (if any). \
Note that the chat history may already contain the answer to the user question, in which case you can \
skip straight to the {CLOSER}, or the user question may be a follow-up to a previous question. \
In any case, do not confuse the below with the user query. It is only there to provide context.
{SEPARATOR_LINE}
---chat_history_string---
{SEPARATOR_LINE}

Also, the current time is ---current_time---. Consider that if the question involves dates or \
time periods.

HINTS:
   - again, as future steps can depend on earlier ones, the steps should be fairly high-level. \
For example, if the question is 'which jiras address the main problems Nike has?', a good plan may be:
   --
   1) identify the main problem that Nike has
   2) find jiras that address the problem identified in step 1
   3) generate the final answer
   --
   - the last step should be something like 'generate the final answer' or maybe something more specific.

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it. \
Also consider the current time if useful for the problem.>",
   "plan": "<the full plan, formatted as a string. See examples above. \
(Note that the plan of record must be a string, not a list of strings! If the question \
refers to dates etc. you should also consider the current time. Also, again, the steps \
should NOT contain the specific tool although it may have been used to construct \
the question. Just show the question.)>"
}}
"""

ORCHESTRATOR_FAST_ITERATIVE_DECISION_PROMPT = f"""
Overall, you need to answer a user query. To do so, you may have to do various searches.

You may already have some answers to earlier searches you generated in previous iterations.

YOUR TASK is to decide which tool to call next, and what specific question/task you want to pose to the tool, \
considering the answers you already got, and guided by the initial plan.

Note:
 - you are planning for iteration ---iteration_nr--- now.
 - the current time is ---current_time---.

You have these ---num_available_tools--- tools available, \
---available_tools---.

---tool_descriptions---

---kg_types_descriptions---

Here is the overall question that you need to answer:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}


Finally, here are the past few chat messages for reference (if any). \
Note that the chat history may already contain the answer to the user question, in which case you can \
skip straight to the {CLOSER}, or the user question may be a follow-up to a previous question. \
In any case, do not confuse the below with the user query. It is only there to provide context.
{SEPARATOR_LINE}
---chat_history_string---
{SEPARATOR_LINE}

Here is the answer history so far (if any) (Note that the answer history may already \
contain the answer to the user question, in which case you can \
skip straight to the {CLOSER}, or the user question may be a follow-up to a previous question. \
In any case, do not confuse the below with the user query. It is only there to provide context.)
{SEPARATOR_LINE}
---answer_history_string---
{SEPARATOR_LINE}


DIFFERENTIATION/RELATION BETWEEN TOOLS:
---tool_differentiation_hints---

MISCELLANEOUS HINTS:
   - please first consider whether you already can answer the question with the information you already have. \
Also consider whether the plan suggests you are already done. If so, you MUST use the "{CLOSER}" tool. \
Do not generate extra questions just because you can!
   - if you think more information is needed because a sub-question was not sufficiently answered, \
you can generate a modified version of the previous step, thus effectively modifying the plan.
   - you can only consider a tool that fits the remaining time budget! The tool cost must be below \
the remaining time budget.
   - be careful NOT TO REPEAT NEARLY THE SAME QUESTION IN THE SAME TOOL AGAIN! If you did not get a \
good answer from one tool you may want to query another tool for the same purpose, but only of the \
other tool seems suitable too!
   - Again, focus is on generating NEW INFORMATION! Try to generate questions that
         - address gaps in the information relative to the original question
         - or are interesting follow-ups to questions answered so far, if you think \
the user would be interested in it.


Here is roughly how you should decide whether you are done to call the {CLOSER} tool:
{DONE_STANDARD[DRTimeBudget.FAST]}

YOUR TASK: you need to construct the next question and the tool to send it to. To do so, please consider \
the original question, the tools you have available, and the answers you have so far \
(either from previous iterations or from the chat history). Make sure that the answer is \
specific to what is needed, and - if applicable - BUILDS ON TOP of the learnings so far in order to get \
new targeted information that gets us to be able to answer the original question. (Note again, that sending \
the request to the {CLOSER} tool is an option if you think the information is sufficient.)

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 1-3 sentences. Think through it like a person would do it.>",
   "next_step": {{"tool": "<---tool_choice_options--->",
                  "questions": "<the question you want to pose to the tool. Note that the \
question should be appropriate for the tool. For example:
---tool_question_hints---]>"}}
}}




"""

ORCHESTRATOR_DEEP_ITERATIVE_DECISION_PROMPT = f"""
Overall, you need to answer a user query. To do so, you have various tools at your disposal that you \
can call iteratively. And an initial plan that should guide your thinking.

You may already have some answers to earlier questions calls you generated in previous iterations, and you also \
have a high-level plan given to you.

Your task is to decide which tool to call next, and what specific question/task you want to pose to the tool, \
considering the answers you already got, and guided by the initial plan.

(You are planning for iteration ---iteration_nr--- now.). Also, the current time is ---current_time---.

You have these ---num_available_tools--- tools available, \
---available_tools---.

---tool_descriptions---

---kg_types_descriptions---

Here is the overall question that you need to answer:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

The current iteration is ---iteration_nr---:

Here is the high-level plan:
{SEPARATOR_LINE}
---current_plan_of_record_string---
{SEPARATOR_LINE}

Here is the answer history so far (if any):
{SEPARATOR_LINE}
---answer_history_string---
{SEPARATOR_LINE}

Finally, here are the past few chat messages for reference (if any). \
Note that the chat history may already contain the answer to the user question, in which case you can \
skip straight to the {CLOSER}, or the user question may be a follow-up to a previous question. \
In any case, do not confuse the below with the user query. It is only there to provide context.
{SEPARATOR_LINE}
---chat_history_string---
{SEPARATOR_LINE}

Here are the average costs of the tools that you should consider in your decision:
{SEPARATOR_LINE}
---average_tool_costs---
{SEPARATOR_LINE}

Here is the remaining time budget you have to answer the question:
{SEPARATOR_LINE}
---remaining_time_budget---
{SEPARATOR_LINE}

DIFFERENTIATION/RELATION BETWEEN TOOLS:
---tool_differentiation_hints---

MISCELLANEOUS HINTS:
   - please first consider whether you already can answer the question with the information you already have. \
Also consider whether the plan suggests you are already done. If so, you can use the "{CLOSER}" tool.
   - if you think more information is needed because a sub-question was not sufficiently answered, \
you can generate a modified version of the previous step, thus effectively modifying the plan.
  - you can only consider a tool that fits the remaining time budget! The tool cost must be below \
the remaining time budget.
  - be careful not to repeat nearly the same question in the same tool again! If you did not get a \
good answer from one tool you may want to query another tool for the same purpose, but only of the \
new tool seems suitable for the question!

  - Again, focus is on generating NEW INFORMATION! Try to generate questions that
      - address gaps in the information relative to the original question
      - or are interesting follow-ups to questions answered so far, if you think the user would be interested in it.
      - checks of whether the original piece of information is correct, or whether it is missing some details.


YOUR TASK:
you need to construct the next question and the tool to send it to. To do so, please consider \
the original question, the high-level plan, the tools you have available, and the answers you have so far \
(either from previous iterations or from the chat history). Make sure that the answer is \
specific to what is needed, and - if applicable - BUILDS ON TOP of the learnings so far in order to get \
new targeted information that gets us to be able to answer the original question. (Note again, that sending \
the request to the CLOSER tool is an option if you think the information is sufficient.)

Here is roughly how you should decide whether you are done to call the {CLOSER} tool:
{DONE_STANDARD[DRTimeBudget.DEEP]}

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "next_step": {{"tool": "<---tool_choice_options--->",
                  "questions": "<the question you want to pose to the tool. Note that the \
question should be appropriate for the tool. For example:
---tool_question_hints---
Also, make sure that each question HAS THE FULL CONTEXT, so don't use questions like \
'show me some other examples', but more like 'some me examples that are not about \
science'.>"}}
}}
"""


BASIC_SEARCH_PROMPTS[
    DRTimeBudget.FAST
] = f"""
You are a helpful assistant that can use the provided documents, the specific search query, and the \
user query that needs to be ultimately answered, to provide a succinct, relevant, and grounded \
answer to the specific search query. Although your response should pertain mainly to the specific search \
query, also keep in mind the base query to provide valuable insights for answering the base query too.

Here is the specific search query:
{SEPARATOR_LINE}
---search_query---
{SEPARATOR_LINE}

Here is the base question that ultimately needs to be answered:
{SEPARATOR_LINE}
---base_question---
{SEPARATOR_LINE}

And here is the list of documents that you must use to answer the specific search query:
{SEPARATOR_LINE}
---document_text---
{SEPARATOR_LINE}

Notes:
   - only use documents that are relevant to the specific search query AND you KNOW apply \
to the context of the question! Example: context is about what Nike was doing to drive sales, \
and the question is about what Puma is doing to drive sales, DO NOT USE ANY INFORMATION \
from the information from Nike! In fact, even if the context does not discuss driving \
sales for Nike but about driving sales w/o mentioning any company (incl. Puma!), you \
still cannot use the information! You MUST be sure that the context is correct. If in \
doubt, don't use that document!
   - It is critical to avoid hallucinations as well as taking information out of context.
   - clearly indicate any assumptions you make in your answer.
   - while the base question is important, really focus on answering the specific search query. \
That is your task.
   - again, do not use/cite any documents that you are not 100% sure are relevant to the \
SPECIFIC context \
of the question! And do NOT GUESS HERE and say 'oh, it is reasonable that this context applies here'. \
DO NOT DO THAT. If the question is about 'yellow curry' and you only see information about 'curry', \
say something like 'there is no mention of yellow curry specifically', and IGNORE THAT DOCUMENT. But \
if you still strongly suspect the document is relevant, you can use it, but you MUST clearly \
indicate that you are not 100% sure and that the document does not mention 'yellow curry'. (As \
an example.)
If the specific term or concept is not present, the answer should explicitly state its absence before \
providing any related information.
   - Always begin your answer with a direct statement about whether the exact term or phrase, or \
the exact meaning was found in the documents.
   - only provide a SHORT answer that i) provides the requested information if the question was \
very specific, ii) cites the relevant documents at the end, and iii) provides a BRIEF HIGH-LEVEL \
summary of the information in the cited documents, and cite the documents that are most \
relevant to the question sent to you.

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 3-6 sentences of what guides you to the answer of \
the specific search query given the documents.
Start out here with a brief statement whether the SPECIFIC CONTEXT is mentioned in the \
documents. (Example: 'I was not able to find information about yellow curry specifically, \
but I found information about curry..'). Any reasoning should be done here. Generate \
here the information that will be necessary to provide a succinct answer to the specific search query. >",
   "answer": "<the specific answer to the specific search query. This may involve some reasoning over \
the documents. Again, start out here as well with a brief statement whether the SPECIFIC CONTEXT is \
mentioned in the \
documents. (Example: 'I was not able to find information about yellow curry specifically, \
but I found information about curry..').
But this should be be precise and concise, and specifically answer the question.>",
"citations": "<the list of document numbers that are relevvant for the answer. \
Please list in format [1][4][6], etc.>"
}}
"""

BASIC_SEARCH_PROMPTS[
    DRTimeBudget.DEEP
] = f"""
You are a helpful assistant that can use the provided documents, the specific search query, and the \
user query that needs to be ultimately answered, to provide a succinct, relevant, and grounded \
analysis to the specific search query. Although your response should pertain mainly to the specific search \
query, also keep in mind the base query to provide valuable insights for answering the base query too.

Here is the specific search query:
{SEPARATOR_LINE}
---search_query---
{SEPARATOR_LINE}

Here is the base question that ultimately needs to be answered:
{SEPARATOR_LINE}
---base_question---
{SEPARATOR_LINE}

And here is the list of documents that you must use to answer the specific search query:
{SEPARATOR_LINE}
---document_text---
{SEPARATOR_LINE}

Notes:
   - only use documents that are relevant to the specific search query AND you KNOW apply \
to the context of the question! Example: context is about what Nike was doing to drive sales, \
and the question is about what Puma is doing to drive sales, DO NOT USE ANY INFORMATION \
from the information from Nike! In fact, even if the context does not discuss driving \
sales for Nike but about driving sales w/o mentioning any company (incl. Puma!), you \
still cannot use the information! You MUST be sure that the context is correct. If in \
doubt, don't use that document!
   - It is critical to avoid hallucinations as well as taking information out of context.
   - clearly indicate any assumptions you make in your answer.
   - while the base question is important, really focus on answering the specific search query. \
That is your task.
   - again, do not use/cite any documents that you are not 100% sure are relevant to the \
SPECIFIC context \
of the question! And do NOT GUESS HERE and say 'oh, it is reasonable that this context applies here'. \
DO NOT DO THAT. If the question is about 'yellow curry' and you only see information about 'curry', \
say something like 'there is no mention of yellow curry specifically', and IGNORE THAT DOCUMENT. But \
if you still strongly suspect the document is relevant, you can use it, but you MUST clearly \
indicate that you are not 100% sure and that the document does not mention 'yellow curry'. (As \
an example.)
If the specific term or concept is not present, the answer should explicitly state its absence before \
providing any related information.
   - Always begin your answer with a direct statement about whether the exact term or phrase, or \
the exact meaning was found in the documents.
   - only provide a SHORT answer that i) provides the requested information if the question was \
very specific, ii) cites the relevant documents at the end, and iii) provides a BRIEF HIGH-LEVEL \
summary of the information in the cited documents, and cite the documents that are most \
relevant to the question sent to you.

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 5-8 sentences of what guides you to your conclusions of \
the specific search query given the documents.
Start out here with a brief statement whether the SPECIFIC CONTEXT is mentioned in the \
documents. (Example: 'I was not able to find information about yellow curry specifically, \
but I found information about curry..'). Any reasoning should be done here. Generate \
here the information that will be necessary to provide a succinct answer to the specific search query. >",
   "answer": "<the specific answer to the specific search query. This may involve some reasoning over \
the documents. Again, start out here as well with a brief statement whether the SPECIFIC CONTEXT is \
mentioned in the \
documents. (Example: 'I was not able to find information about yellow curry specifically, \
but I found information about curry..').
But this should be be precise and concise, and specifically answer the question. Please cite \
the document sources inline in format [1][7], etc.>",
"claims": "<a list of short claims discussed in the documents as they pertain to the query and/or \
the original question. These will later be used for follow-up questions and verifications. Note that \
these may not actually be in the succinct answer above. Also here, please cite the \
document sources inline in format [1][7], etc.. So this should have format like \
[<claim 1>, <claim 2>, <claim 3>, ...], each with citations.>",
"citations": "<the list of document numbers that are relevvant for the answer and appeared as \
citations earlier. Please list in format [1][4][6], etc.>"
}}
"""

TOOL_PROCESSING_PROMPT = f"""
You are a helpful assistant that is great at summarizing and processing the \
response of a tool as it is relevent to a broader user question. You can use the \
provided documents, the specific task sent to the tool, \
and the \
overall user query that needs to be ultimately answered, to provide a succinct, relevant, and grounded \
answer for a specific task directed to thetool. Although your response should \
pertain mainly to the specific task \
query, also keep in mind the base query to provide valuable insights for answering the main too.

Here is the specific task query:
{SEPARATOR_LINE}
---query---
{SEPARATOR_LINE}

Here is the base question that ultimately needs to be answered:
{SEPARATOR_LINE}
---base_question---
{SEPARATOR_LINE}

And here is the list of documents that you must use to answer the specific search query:
{SEPARATOR_LINE}
---document_text---
{SEPARATOR_LINE}

Notes:
   - only use documents that are relevant to the specific task AND you KNOW apply \
to the context of the question! Example: context is about what Nike was doing to drive sales, \
and the question is about what Puma is doing to drive sales, DO NOT USE ANY INFORMATION \
from the information from Nike! In fact, even if the context does not discuss driving \
sales for Nike but about driving sales w/o mentioning any company (incl. Puma!), you \
still cannot use the information! You MUST be sure that the context is correct. If in \
doubt, don't use that document!
   - It is critical to avoid hallucinations as well as taking information out of context.
   - clearly indicate any assumptions you make in your answer.
   - while the base question is important, really focus on answering the specific search query. \
That is your task.
   - again, do not use/cite any documents that you are not 100% sure are relevant to the \
SPECIFIC context \
of the question! And do NOT GUESS HERE and say 'oh, it is reasonable that this context applies here'. \
DO NOT DO THAT. If the question is about 'yellow curry' and you only see information about 'curry', \
say something like 'there is no mention of yellow curry specifically', and IGNORE THAT DOCUMENT. But \
if you still strongly suspect the document is relevant, you can use it, but you MUST clearly \
indicate that you are not 100% sure and that the document does not mention 'yellow curry'. (As \
an example.)
If the specific term or concept is not present, the answer should explicitly state its absence before \
providing any related information.
   - Always begin your answer with a direct statement about whether the exact term or phrase, or \
the exact meaning was found in the documents.
   - only provide a SHORT answer that i) provides the requested information if the question was \
very specific, ii) cites the relevant documents at the end, and iii) provides a BRIEF HIGH-LEVEL \
summary of the information in the cited documents, and cite the documents that are most \
relevant to the question sent to you.

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 3-6 sentences of what guides you to the answer of \
the specific search query given the documents.
Start out here with a brief statement whether the SPECIFIC CONTEXT is mentioned in the \
documents. (Example: 'I was not able to find information about yellow curry specifically, \
but I found information about curry..'). Any reasoning should be done here. Generate \
here the information that will be necessary to provide a succinct answer to the specific search query. >",
   "answer": "<the specific answer to the specific search query. This may involve some reasoning over \
the documents. Again, start out here as well with a brief statement whether the SPECIFIC CONTEXT is \
mentioned in the \
documents. (Example: 'I was not able to find information about yellow curry specifically, \
but I found information about curry..').
But this should be be precise and concise, and specifically answer the question.>",
"citations": "<the list of document numbers that are relevvant for the answer. \
Please list in format [1][4][6], etc.>"
}}
"""

FINAL_ANSWER_PROMPT = f"""
You are a helpful assistant that can answer a user question based on sub-answers generated earlier \
and a list of documents that were used to generate the sub-answers. The list of documents is \
for further reference to get more details.

Here is the question that needs to be answered:
{SEPARATOR_LINE}
---base_question---
{SEPARATOR_LINE}

Here is the list of sub-questions, their answers, and the corresponding documents:
{SEPARATOR_LINE}
---iteration_responses_string---
{SEPARATOR_LINE}

Finally, here is the previous chat history (if any), which may contain relevant information \
to answer the question:
{SEPARATOR_LINE}
---chat_history_string---
{SEPARATOR_LINE}


GUIDANCE:
 - note that the sub-answers to the sub-questions are designed to be high-level, mostly \
focussing on providing the citations and providing some answer facts. But the \
main content should be in the cited documents for each sub-question.
 - Pay close attention to whether the sub-answers mention whether the topic of interest \
was explicitly mentioned! If not you cannot reliably use that information to construct your answer, \
or you MUST then qualify your answer with something like 'xyz was not explicitly \
mentioned, however the similar concept abc was, and I learned...'
- if the documents/sub-answers do not explicitly mention the topic of interest with \
specificity(!) (example: 'yellow curry' vs 'curry'), you MUST sate at the outset that \
the provided context os based on the less specific concept. (Example: 'I was not able to \
find information about yellow curry specifically, but here is what I found about curry..'
- make sure that the text from a document that you use is NOT TAKEN OUT OF CONTEXT!
- do not make anything up! Only use the information provided in the documents, or, \
if no documents are provided for a sub-answer, in the actual sub-answer.
- Provide a thoughtful answer that is concise and to the point, but that is detailed.
- Please cite your sources inline in format [2][4], etc! The numbers of the documents \
are provided above.

ANSWER:
"""

GET_CLARIFICATION_PROMPT = f"""
You are a helpful assistant that is great at asking clarifying questions in case \
a base question is not as clear enough. Your task is to ask necessary clarification \
questions to the user, before the question is sent to the deep research agent.

Your task is NOT to answer the question. Instead, you must gather necessary information \
based on the available tools and their capabilities described below. If a tool does not \
absolutely require a specific detail, you should not ask for it. It is fine for a question \
to be vague, as long as the tool can handle it. Also keep in mind that the user may simply \
enter a keyword without providing context or specific instructions. In those cases \
assume that the user is conducting a general search on the topic.

You have these ---num_available_tools--- tools available, ---available_tools---.

In case the knowledge graph is used, here is the description of the entity and relationship types:
---kg_types_descriptions---

The tools and the entity and relationship types in the knowledge graph are simply provided \
as context for determining whether the question requires clarification.

Here is the question the user asked:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

Here is the previous chat history (if any), which may contain relevant information \
to answer the question:
{SEPARATOR_LINE}
---chat_history_string---
{SEPARATOR_LINE}

NOTES:
  - you have to reason over this purely based on your intrinsic knowledge.
  - if clarifications are required, fill in 'true' for "feedback_needed" field and \
articulate UP TO 3 NUMBERED clarification questions that you think are needed to clarify the question.
Use the format: '1. <question 1>\n2. <question 2>\n3. <question 3>'.
Note that it is fine to ask zero, one, two, or three follow-up questions.
  - if no clarifications are required, fill in 'false' for "feedback_needed" field and \
"no feedback required" for "feedback_request" field.
  - only ask clarification questions if that information is VITAL to answer the user question. \
Do NOT simply ask followup questions that tries to expand on the user question, or gather more details \
which may not be absolutely necessary for the deep research agent to answer the user question.

EXAMPLES:
1. User question: "What is the capital of France?"
   Feedback needed: false
   Feedback request: 'no feedback request'
   Reason: The user question is clear and does not require any clarification.


2. User question: "How many tickets are there?"
   Feedback needed: true
   Feedback request: '1. What do you refer to by "tickets"?'
   Reason: 'Tickets' could refer to many objects, like service tickets, jira tickets, etc. \
But besides this, no further information is needed and asking one clarification question is enough.

3. User question: "How many PRs were merged last month?"
   Feedback needed: true
   Feedback request: '1. Do you have a specific repo in mind for the Pull Requests?'
   Reason: 'Merged' strongly suggests that PRs refer to pull requests. So this does \
not need to be further clarified. However, asking for the repo is quite important as \
typically there could be many. But besides this, no further information is needed and \
asking one clarification question is enough.


4. User question: "What are the most recent PRs about?"
   Feedback needed: true
   Feedback request: '1. What do PRs refer to? Pull Requests or something else?\
\n2. What does most recent mean? Most recent <x> PRs? Or PRs from this week? \
Please clarify.\n3. What is the activity for the time measure? Creation? Closing? Updating? etc.'
   Reason: We need to clarify what PRs refers to. Also 'most recent' is not well defined \
and needs multiple clarifications.


5. User question: "Compare Adidas and Puma"
   Feedback needed: true
   Feedback request: '1. Do you have specific areas you want the comparison to be about?\
\n2. Are you looking at a specific time period?\n3. Do you want the information in a \
specific format?'
   Reason: This question is overly broad and it really requires specification in terms of \
areas and time period (therefore, clarification questions 1 and 2). Also, the user may want to \
compare in a specific format, like table vs text form, therefore clarification question 3. \
Certainly, there could be many more questions, but these seem to be themost essential 3.


Please respond with a json dictionary in the following format:
{{
   "clarification_needed": <true or false, whether you believe a clarification question is \
needed based on above guidance>,
   "clarification_question": "<the clarification questions if clarification_needed is true, \
otherwise say 'no clarification needed'. Respond as a string, not as a list, even if you \
think multiple clarification questions are needed.>"
}}

ANSWER:
"""
