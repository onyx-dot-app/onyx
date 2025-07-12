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

On the other hand, while the "KNOWLEDGE_GRAPH" tool also generates answers based on generated \
documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
the entities and relationships in a question and then analyzing the documents correcponding to the \
entities to answer the question. The KNOWLEDGE_GRAPH tool can also answer aggregation-type questions \
like 'how many jiras did each employee close last month?'. HOWEVER, the KNOWLEDGE_GRAPH tool \
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
'fact-like' searches using connected documents.

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
as the next_step field.>"
}}
"""
