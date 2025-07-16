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

DR_TOOLS_DESCRIPTIONS = f"""\
You have three tools available, "{SEARCH}", "{KNOWLEDGE_GRAPH}", and "{CLOSER}".

- The "{SEARCH}" tool is used to answer questions that can be answered using the information \
present in the connected documents.
Note that the search tool is not well suited for time-ordered \
questions ('...latest email...', '... last 2 jiras resolved...' etc.) and answering aggregation-type \
questions (unless that info is present in the connected documents). \
For answering those type of questions, you should use the {KNOWLEDGE_GRAPH} tool instead. The \
{SEARCH} tool supports parallel calls.

- The "{KNOWLEDGE_GRAPH}" tool also generates answers based on the connected documents, but in a \
entity/relationship-centric way, making it suitable for answering complex questions about specific \
entities and relationships, such as "summarize the open tickets assigned to John in the last month". \
It can also query a relational database containing the entities and relationships, allowing it to \
answer aggregation-type questions like 'how many jiras did each employee close last month?'. \
The {KNOWLEDGE_GRAPH} tool MUST ONLY BE USED if the question really fits the entity/relationship \
types that are available in the knowledge graph!


However, the {KNOWLEDGE_GRAPH} tool is slower than the {SEARCH} tool, and it can only be used for \
entity and relationship types that are available in the knowledge graph, listed later.
Again, a question to the {KNOWLEDGE_GRAPH} tool can also analyze the relevant documents/entities, \
not merely find them.

NOTE:

- The "{CLOSER}" tool does not directly have access to the documents, but it can use the results from \
previous iterations to generate a comprehensive final answer. It should always be called exactly once \
at the very end to consolidate the gathered information, run any comparisons if needed, and pick out \
the most relevant information to answer the question. You can also skip straight to the {CLOSER} \
if there is sufficient information in the provided history to answer the question.
"""

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


FAST_PLAN_GENERATION_PROMPT = f"""
You need to route a user query request to the appropriate tool, given the following tool \
descriptions, as well as previous chat context.

{DR_TOOLS_DESCRIPTIONS}

{KG_TYPES_DESCRIPTIONS}

Here is the user query that you need to route:
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


HINTS:
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
   - again, use the chat history (if provided) to see if you can skip straight to the {CLOSER}.


Please answer ONLY with '{SEARCH}', '{KNOWLEDGE_GRAPH}', or '{CLOSER}'.

ANSWER:
"""

PLAN_GENERATION_PROMPT = f"""
You are a great Assistant that is an expert at analyzing a question and breaking it up into a \
series of high-level, answerable sub-questions.

Given the user query and the list of available tools, your task is to devise a high-level plan \
consisting of a list of the iterations, each iteration consisting of the \
apsects to investigate, so that by the end of the process you have gathered sufficient \
information to generate a well-researched and highly relevant answer to the user query.

Note that the plan will only be used as a guideline, and a separate agent will use your plan along \
with the results from previous iterations to generate the specific questions to send to the tool for each \
iteration. Thus you should not be too specific in your plan as some steps could be dependent on \
previous steps.

Assume that all steps will be executed sequentially, so the answers of earlier steps will be known \
at later steps. To capture that, you can refer to earlier results in later steps. (Example of a 'later'\
question: 'find information for each result of step 3.')

{DR_TOOLS_DESCRIPTIONS}

{KG_TYPES_DESCRIPTIONS}

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


HINTS:
   - again, as future steps can depend on earlier ones, the steps should be fairly high-level. \
For example, if the question is 'which jiras address the main problems Nike has?', a good plan may be:
   --
   1) identify the main problem that Nike has
   2) find jiras that address the problem identified in step 1
   3) generate the final answer
   --
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.\
(This is important to ask well-structured questions, although the tool itself wil not be shown later.)
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
   - use parallel calls to the {SEARCH} tool to your advantage to save time!
   - again, use the chat history (if provided) to see if you can skip straight to the {CLOSER} tool to generate \
the final answer. If so, simply state 'generate the final answer' in your plan.

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "plan": "<the full plan, formatted as a string. See examples above. \
(Note that the plan of record must be a string, not a list of strings! Also, again, the steps \
should NOT contain the specific tool although it may have been used to construct \
the question. Just show the question.)>"
}}
"""

SEQUENTIAL_ITERATIVE_DR_SINGLE_PLAN_DECISION_PROMPT = f"""
Overall, you need to answer a user query. To do so, you have various tools at your disposal that you \
can call iteratively. And an initial plan that should guide your thinking.

You may already have some answers to earlier questions calls you generated in previous iterations, and you also \
have a high-level plan given to you.

Your task is to decide which tool to call next, and what specific question/task you want to pose to the tool, \
considering the answers you already got, and guided by the initial plan.

(You are planning for iteration ---iteration_nr--- now.).

{DR_TOOLS_DESCRIPTIONS}

{KG_TYPES_DESCRIPTIONS}

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


HINTS:
   - please first consider whether you can answer the question with the information you already have. \
Also consider whether the plan suggests you are already done. If so, you can use the "{CLOSER}" tool.
   - if you think more information is needed because a sub-question was not sufficiently answered, \
you can generate a modified version of the previous step, thus effectively modifying the plan.
   - please look at the user query and the entity types and relationship types in the knowledge graph \
to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
   - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
'search for this'-type of question, then also use '{SEARCH}'.
   - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
   - the {KNOWLEDGE_GRAPH} tool can also analyze the relevant documents/entities, so DO NOT \
   try to first find socuments and then analyze them in a future iteration. Query the {KNOWLEDGE_GRAPH} \
   tool directly, like 'summarize the most recent jira created by John'.
   - you can only send one request to each tool.

YOUR TASK: you need to construct the next question and the tool to send it to. To do so, please consider \
the original question, the high-level plan, the tools you have available, and the answers you have so far \
(either from previous iterations or from the chat history). Make sure that the answer is \
specific to what is needed, and - if applicable - BUILDS ON TOP of the learnings so far in order to get \
new targetted information that gets us to be able to answer the original question. (Note again, that sending \
the request to the CLOSER tool is an option if you think the information is sufficient.)


Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
guided by the question you need to answer, the answers you have so far, and the plan of record.>",
   "next_step": {{"tool": "<{SEARCH} or {KNOWLEDGE_GRAPH} or {CLOSER}>",
                  "questions": "<the question you want to pose to the tool. Note that the \
question should be appropriate for the tool. For example, if the tool is {SEARCH}, the question should be \
written as a search query.>"}}
}}
"""


# ITERATIVE_DR_DECISION__NO_PLAN_PROMPT = f"""
# Overall, you need to answer a user query. To do so, you have various tools at your disposal that you \
# can call iteratively.

# You may already have some answers to questions/tool calls you generated in previous iterations.

# Your task now is to decide which tool to call next, and what question/task you want to pose to the tool, \
# considering the answers you already got.

# You have three tools available, "{SEARCH}", "{KNOWLEDGE_GRAPH}", and "{CLOSER}".

# - The "SEARCH" tool is used to answer questions that can be answered by one or more standard \
# 'fact-like' searches using connected documents. Note that time-ordering does not work well with \
# the {SEARCH} tool, and - if the entities in question are in the Knowledge Graph - you should \
# use the {KNOWLEDGE_GRAPH} tool below instead.

# - On the other hand, while the "{KNOWLEDGE_GRAPH}" tool also generates answers based on generated \
# documents, it is doing so in a very entity/relationship-centric way, for example first identifying \
# the entities and relationships in a question and then analyzing the documents correcponding to the \
# entities to answer the question. The {KNOWLEDGE_GRAPH} tool can also answer aggregation-type questions \
# like 'how many jiras did each employee close last month?'. HOWEVER, the {KNOWLEDGE_GRAPH} tool \
# can only be used for entity types and relationship types that are available in the knowledge graph!

# Here are the entity types that are available in the knowledge graph:
# {SEPARATOR_LINE}
# ---possible_entities---
# {SEPARATOR_LINE}

# Here are the relationship types that are available in the knowledge graph:
# {SEPARATOR_LINE}
# ---possible_relationships---
# {SEPARATOR_LINE}

# - Lastly, the "CLOSER" tool is not really a tool but the signal that all of the information required to \
# answer the question has been gathered, and we can move to final answering.


# Here is the overall question that you need to answer:
# {SEPARATOR_LINE}
# ---question---
# {SEPARATOR_LINE}

# The current iteration is ---iteration_nr---:

# Here is the answer history so far (if any):
# {SEPARATOR_LINE}
# ---answer_history_string---
# {SEPARATOR_LINE}


# HINTS:
# - please first consider whether you can answer the question with the information you already have. \
# If you can, you can use the "CLOSER" tool.
# - if you think more information is needed, look at the original question, the answers you have so far.
# Note:
#    - please look at the user query and the entity types and relationship types in the knowledge graph \
# to see whether the question can be answered by the {KNOWLEDGE_GRAPH} tool at all. If not, use '{SEARCH}'.
#    - if the question can be answered by the {KNOWLEDGE_GRAPH} tool, but the question seems like a standard \
# 'search for this'-type of question, then also use '{SEARCH}'.
#    - also consider whether the user query implies whether a standard search query should be used or a \
# knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
# whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.
# - if the {SEARCH} tool is chosen, remember that you can iterate and do multiple search queries. \
# Therefore, if there are multiple objects in the question, or there are ambiguous terms, you want \
# prepare the plan for multiple search queries over multiple generation with the goal of having \
# each search query be quite specific! So if the question is for example like 'compare A vs B', \
# then you probably want to generate at least two searches, one focussed on A and a second on B. \
# (Note though that the fact that later A and B will be compared in this example, the question about A \
# may get informed as in 'find features of A for comparison with another entity' )

# Please format your answer as a json dictionary in the following format:
# {{
#    "reasoning": "<your reasoning in 2-4 sentences. Think through it like a person would do it, \
# guided by the question you need to answer, the answers you have so far, and the plan of record.>",
#    "next_step": {{"tool": "<{SEARCH} or {KNOWLEDGE_GRAPH} or {CLOSER}>",
#                   "questions": "<the list of questions you want to pose to the tool. Note that the \
# questions should be appropriate for the tool. For example, if the tool is {SEARCH}, the question should be \
# written as a search query. Format it as a list of strings.>"}}
# }}
# """


BASIC_SEARCH_PROMPT = f"""
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

Note:
   - only use documents that are relevant to the specific search query AND you KNOW apply to the \
context of the question. It is critical to avoid hallucinations as well as taking information \
out of context.
   - clearly indicate any assumptions you make in your answer.
   - while the base question is important, really focus on answering the specific search query. \
That is your task.
   - only provide a SHORT answer that i) provides the requested information if the question was very \
specific, ii) cites the relevant documents at the end, and iii) provides a BRIEF HIGH-LEVEL summary of \
the information in the cited documents, and cite the documents that are most relevent to the question \
sent to you.

Please format your answer as a json dictionary in the following format:
{{
   "reasoning": "<your reasoning in 3-6 sentences of what guides you to the answer of \
the specific search query given the documents. Any reasoning should be done here. Generate \
here the information that will be necessary to provide a succinct answer to the specific search query.>",
   "answer": "<the specific answer to the specific search query. This may involve some reasoning over \
the documents. But this should be be precise and concise, and specifically answer the question.>",
"citations": "<the list of document numbers that are relevevant for the answer. \
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
- make sure that a the text from a document that you use is NOT TAKEN OUT OF CONTEXT!
- do not make anything up! Only use the information provided in the documents, or, \
if no documents are provided for a sub-answer, in the actual sub-answer.
- Provide a thoughtful answer that is concise and to the point, but that is detailed.
- Please cite your sources inline in format [2][4], etc! The numbers of the documents \
are provided above.

ANSWER:
"""
