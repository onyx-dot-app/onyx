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


FAST_DR_DECISION_PROMPT = f"""
You need to route a user query request to the appropriate tool.

You have two tools available, "{SEARCH}" and "{KNOWLEDGE_GRAPH}".

The "SEARCH" tool is used to answer questions that can be answered by one or more standard \
'fact-like' searches using connected documents.

On the other hand, while the "{KNOWLEDGE_GRAPH}" tool also generates answers based on generated \
documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
the entities and relationships in a question and then analyzing the documents correcponding to the \
entities to answer the question. The {KNOWLEDGE_GRAPH} tool can also answer aggregation-type questions \
like 'how many jiras did each employee close last month?'. HOWEVER, the {KNOWLEDGE_GRAPH} tool \
can only be used for entity types and relationship types that are available in the knowledge graph!

Here are the entity types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_entities---
{SEPARATOR_LINE}

Here are the relationship types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_relationships---
{SEPARATOR_LINE}

And finally here is the user query that you need to route:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

HINTS:
- please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
- if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
- also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.


Please answer ONLY with '{SEARCH}' or '{KNOWLEDGE_GRAPH}'.

ANSWER:
"""

ITERATIVE_DR_DECISION_PROMPT = f"""
Overall, you need to answer a user query. To do so, you have various tools at your disposal that you \
can call iteratively.

You may already have some answers to questions/tool calls you generated in previous iterations, and you also \
may have a plan of record.

Your task now is to:
  1) decide which tool to call next, and what question/task you want to pose to the tool, \
considering the answers you already got,
  2) update - if necessary - the plan of record,


You have three tools available, "{SEARCH}", "{KNOWLEDGE_GRAPH}", and "{CLOSER}".

- The "SEARCH" tool is used to answer questions that can be answered by one or more standard \
'fact-like' searches using connected documents. Note that time-ordering does not work well with \
the {SEARCH} tool, and - if the entities in question are in the Knowledge Graph - you should \
use the {KNOWLEDGE_GRAPH} tool below instead.

- On the other hand, while the "{KNOWLEDGE_GRAPH}" tool also generates answers based on generated \
documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
the entities and relationships in a question and then analyzing the documents correcponding to the \
entities to answer the question. The {KNOWLEDGE_GRAPH} tool can also answer aggregation-type questions \
like 'how many jiras did each employee close last month?'. HOWEVER, the {KNOWLEDGE_GRAPH} tool \
can only be used for entity types and relationship types that are available in the knowledge graph!

Here are the entity types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_entities---
{SEPARATOR_LINE}

Here are the relationship types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_relationships---
{SEPARATOR_LINE}

- Lastly, the "CLOSER" tool is not really a tool but the signal that all of the information required to \
answer the question has been gathered, and we can move to final answering.


Here is the overall question that you need to answer:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

The current iteration is ---iteration_nr---:

Here is the current plan of record (if any):
{SEPARATOR_LINE}
---current_plan_of_record_string---
{SEPARATOR_LINE}

Here is the answer history so far (if any):
{SEPARATOR_LINE}
---answer_history_string---
{SEPARATOR_LINE}



HINTS:
- please first consider whether you can answer the question with the information you already have. \
If you can, you can use the "CLOSER" tool.
- if you think more information is needed, look at the original question, the answers you have so far, \
and - for guidance - the plan of record. The plan of record may actually suggest which tool you should \
call next, but you are free, considering the information you have, to make a different decision.
Note:
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
- if the {SEARCH} tool is chosen, remember that you can iterate and do multiple search queries. \
Therefore, if there are multiple objects in the question, or there are ambiguous terms, you want \
prepare the plan for multiple search queries over multiple generation with the goal of having \
each search query be quite specific! So if the question is for example like 'compare A vs B', \
then you probably want to generate at least two searches, one focussed on A and a second on B. \
(Note though that the fact that later A and B will be compared in this example, the question about A \
may get informed as in 'find features of A for comparison with another entity' )
- the plan of record should be complete! I.e., all steps should be included that are believed \
to be necessary to answer the question.
- the plan of record should always end with a call to the {CLOSER} tool.
- if you make a different decision that what the plan of record suggests, please update the plan of record.



Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "next_step": {{"tool": "<{SEARCH} or {KNOWLEDGE_GRAPH} or {CLOSER}>",
                  "questions": "<the list of questions you want to pose to the tool. Note that the \
questions should be appropriate for the tool. For example, if the tool is {SEARCH}, the question should be \
written as a search query. Format it as a list of strings.>"}},
   "plan_of_record": "<the updated full plan of record, formatted as a list of steps in the same format \
as the next_step field. Example:
--
'1. Perform a SEARCH for '...'
2. Perform a KNOWLEDGE_GRAPH analysis for '...'
3. Go to the CLOSER tool.'
(Note that the plan of record must be a string, not a list of strings! Also, each step must refer to \
a specific tool, and what you want the tool to do.)
-->"
}}
"""

PLAN_GENERATION_PROMPT = f"""
You are a great Assistant that is an expert at analyzing a business questions  and \
ORGANIZING the breaking it up into a series of well-defined answerable sub-questions.

More specifically, your task is to take a user question and, given a set of tools that are \
provided to you, construct a series of calls to tools with high-level questions to send to \
the tools such that the generated answers and retrieved documents should provide sufficient \
information to then generate a well-researched answer to the original user question. (Some \
questions will need to be high-level as future steps may depend on the responses to earlier \
answers, so those steps should articulate the goal. A different model with access to \
previous answers will generate later the precise sub-questions to send to the tools.)

You have three tools available, "{SEARCH}", "{KNOWLEDGE_GRAPH}", and "{CLOSER}".

- The "SEARCH" tool is used to answer questions that can be answered by one or more standard \
'fact-like' searches using connected documents. Note that time-ordering does not work well with \
the {SEARCH} tool, and - if the entities in question are in the Knowledge Graph - you should \
use the {KNOWLEDGE_GRAPH} tool below instead.

- On the other hand, while the "{KNOWLEDGE_GRAPH}" tool also generates answers based on generated \
documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
the entities and relationships in a question and then analyzing the documents correcponding to the \
entities to answer the question. The {KNOWLEDGE_GRAPH} tool can also answer aggregation-type questions \
like 'how many jiras did each employee close last month?'. HOWEVER, the {KNOWLEDGE_GRAPH} tool \
can only be used for entity types and relationship types that are available in the knowledge graph!

Here are the entity types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_entities---
{SEPARATOR_LINE}

Here are the relationship types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_relationships---
{SEPARATOR_LINE}

Note that the {KNOWLEDGE_GRAPH} tool can find and analyzer documents in one iteration. \
So 'summarize the last call with Nike' is a good question to send to the {KNOWLEDGE_GRAPH} \
question (if calls and accounts are available in the knowledge graph). DON'T make this \
2 calls as first finding and then summarizing the document. You only have to \
do that if you need to use multiple tools.

- Lastly, the "CLOSER" tool is not really a tool but the signal that all of the information required to \
answer the question has been gathered, and we can move to final answering.


Here is the question that you need to convert into a series of too calls with questions to the tools:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

NOTES:
 - again, as future steps can depend on earlier ones, the questions should be high-level \
and articulate the goal. A different model with access to previous answers will generate later \
the precise sub-questions to send to the tools. As an example, if the question were 'which \
jiras address the main problem that Nike has?', a good plan may be:
--
'1) KNOWLEDGE_GRAPH: identify the main problem that Nike has
2) SEARCH: find jiras that address the problem identified in step 1
3) CLOSER: generate the final answer'

The iterative process of sending questions to tools and retrieveing answers will return the \
main problem in step 1, and another model can then construct the specific question actually sent \
to the SEARCH in step 2, guided by the answer from step 1 and the guidance provided by the plan \
above.
--


HINTS:
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
- the plan must be complete! I.e., all steps should be included that are believed \
to be necessary to answer the question, including the final call to the {CLOSER} tool.


Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "plan": "<the full plan, formatted as a string. Example:
--
1) KNOWLEDGE_GRAPH: identify the main problem that Nike has
2) SEARCH: find jiras that address the problem identified in step 1
3) CLOSER: generate the final answer
--
(Note that the plan of record must be a string, not a list of strings! Also, each step must refer to \
a specific tool, and what you want the tool to do.)>"
}}
"""

ITERATIVE_DR_SINGLE_PLAN_DECISION_PROMPT = f"""
Overall, you need to answer a user query. To do so, you have various tools at your disposal that you \
can call iteratively. And an initial plan that should guide your thinking.

You may already have some answers to earlier questions calls you generated in previous iterations, and you also \
have a high-level plan given to you.

Your task is to decide which tool to call next, and what specific question/task you want to pose to the tool, \
considering the answers you already got, and guided by the initial plan.

(You are on iteration ---iteration_nr---. Consider that when you consider the previous answers and the \
initial plan (which may have gotten modified)).

You have three tools available, "{SEARCH}", "{KNOWLEDGE_GRAPH}", and "{CLOSER}".

- The "SEARCH" tool is used to answer questions that can be answered by one or more standard \
'fact-like' searches using connected documents. Note that time-ordering does not work well with \
the {SEARCH} tool, and - if the entities in question are in the Knowledge Graph - you should \
use the {KNOWLEDGE_GRAPH} tool below instead.

- On the other hand, while the "{KNOWLEDGE_GRAPH}" tool also generates answers based on generated \
documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
the entities and relationships in a question and then analyzing the documents correcponding to the \
entities to answer the question. The {KNOWLEDGE_GRAPH} tool can also answer aggregation-type questions \
like 'how many jiras did each employee close last month?'. HOWEVER, the {KNOWLEDGE_GRAPH} tool \
can only be used for entity types and relationship types that are available in the knowledge graph!

Here are the entity types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_entities---
{SEPARATOR_LINE}

Here are the relationship types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_relationships---
{SEPARATOR_LINE}

- Lastly, the "CLOSER" tool is not really a tool but the signal that all of the information required to \
answer the question has been gathered, and we can move to final answering.


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


HINTS:
- please first consider whether you can answer the question with the information you already have. \
Look also whether the plan suggested you are done.If you can, you can use the "CLOSER" tool.
- if you think more information is needed because a sub-question was not sufficiently answered, \
you can generate a modified version of the previous step, thus effectively modifying the plan.
Note:
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
- if the {SEARCH} tool is chosen, remember that you can iterate and do multiple search queries. \
Therefore, if there are multiple objects in the question, or there are ambiguous terms, you want \
prepare the plan for multiple search queries over multiple generation with the goal of having \
each search query be quite specific! So if the question is for example like 'compare A vs B', \
then you probably want to generate at least two searches, one focussed on A and a second on B. \
(Note though that the fact that later A and B will be compared in this example, the question about A \
may get informed as in 'find features of A for comparison with another entity' )


Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "next_step": {{"tool": "<{SEARCH} or {KNOWLEDGE_GRAPH} or {CLOSER}>",
                  "questions": "<the list of questions you want to pose to the tool. Note that the \
questions should be appropriate for the tool. For example, if the tool is {SEARCH}, the question should be \
written as a search query. Format it as a list of strings.>"}}
}}
"""


ITERATIVE_DR_DECISION__NO_PLAN_PROMPT = f"""
Overall, you need to answer a user query. To do so, you have various tools at your disposal that you \
can call iteratively.

You may already have some answers to questions/tool calls you generated in previous iterations.

Your task now is to decide which tool to call next, and what question/task you want to pose to the tool, \
considering the answers you already got.

You have three tools available, "{SEARCH}", "{KNOWLEDGE_GRAPH}", and "{CLOSER}".

- The "SEARCH" tool is used to answer questions that can be answered by one or more standard \
'fact-like' searches using connected documents. Note that time-ordering does not work well with \
the {SEARCH} tool, and - if the entities in question are in the Knowledge Graph - you should \
use the {KNOWLEDGE_GRAPH} tool below instead.

- On the other hand, while the "{KNOWLEDGE_GRAPH}" tool also generates answers based on generated \
documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
the entities and relationships in a question and then analyzing the documents correcponding to the \
entities to answer the question. The {KNOWLEDGE_GRAPH} tool can also answer aggregation-type questions \
like 'how many jiras did each employee close last month?'. HOWEVER, the {KNOWLEDGE_GRAPH} tool \
can only be used for entity types and relationship types that are available in the knowledge graph!

Here are the entity types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_entities---
{SEPARATOR_LINE}

Here are the relationship types that are available in the knowledge graph:
{SEPARATOR_LINE}
---possible_relationships---
{SEPARATOR_LINE}

- Lastly, the "CLOSER" tool is not really a tool but the signal that all of the information required to \
answer the question has been gathered, and we can move to final answering.


Here is the overall question that you need to answer:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

The current iteration is ---iteration_nr---:

Here is the answer history so far (if any):
{SEPARATOR_LINE}
---answer_history_string---
{SEPARATOR_LINE}



HINTS:
- please first consider whether you can answer the question with the information you already have. \
If you can, you can use the "CLOSER" tool.
- if you think more information is needed, look at the original question, the answers you have so far.
Note:
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
- if the {SEARCH} tool is chosen, remember that you can iterate and do multiple search queries. \
Therefore, if there are multiple objects in the question, or there are ambiguous terms, you want \
prepare the plan for multiple search queries over multiple generation with the goal of having \
each search query be quite specific! So if the question is for example like 'compare A vs B', \
then you probably want to generate at least two searches, one focussed on A and a second on B. \
(Note though that the fact that later A and B will be compared in this example, the question about A \
may get informed as in 'find features of A for comparison with another entity' )

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "next_step": {{"tool": "<{SEARCH} or {KNOWLEDGE_GRAPH} or {CLOSER}>",
                  "questions": "<the list of questions you want to pose to the tool. Note that the \
questions should be appropriate for the tool. For example, if the tool is {SEARCH}, the question should be \
written as a search query. Format it as a list of strings.>"}}
}}
"""


BASIC_SEARCH_PROMPT = """
You are a helpful assistant that can answer a specific search query based on a list of documents and \
also considering the base question that ultimately needs to be answered. (So keep the base question \
in mind when you answer the specific search query. But answer the specific search query IS THE TASK.)

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

Note:
 - only use documents that are relevant to the specific search query AND you KNOW apply to the \
context of the question. It is critical to avoid hallucinations as well as taking information \
out of context.
 - while the base question is important, really focus on answering the specific search query. \
That is your task.
 - CRITICAL: cite the sources (by document number) at the end! Please use the \
format [1], [4], [6], etc.
 - only provide a SHORT answer that i) provides the requested information if the question \
 was very specific, ii) cites the relevant documents at the end, and iii) provides \
a BRIEF HIGH_LEVEL summary of the information in the cited documents, \
 and cites the documents that are most relevent to the question sent to you.

ANSWER:
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

GUIDANCE:
 - note that the sub-answers to the sub-questions are designed to be high-level, mostly \
focussing on providing the citations and providing some answer facts. But the \
main content should be in the cited documents for each sub-question.
- make sure that a the text from a document that you use is NOT TAKEN OUT OF CONTEXT!
- do not make anything up! Only use the information provided in the documents, or, \
if no documents are provided for a sub-answer, in the actual sub-answer.
- Provide a thoughtful answer that is concise and to the point, but that is detailed.
- Please cite your sources inline in format [2], [4], etc! The numbers of the documents \
are provided above.

ANSWER:
"""
