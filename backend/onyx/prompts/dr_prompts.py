# Standards
SEPARATOR_LINE = "-------"
SEPARATOR_LINE_LONG = "---------------"
NO_EXTRACTION = "No extraction of knowledge graph objects was feasible."
YES = "yes"
NO = "no"

# Framing/Support/Template Prompts
ENTITY_TYPE_SETTING_PROMPT = f"""
{SEPARATOR_LINE}
{{entity_types}}
{SEPARATOR_LINE}
""".strip()

RELATIONSHIP_TYPE_SETTING_PROMPT = f"""
Here are the types of relationships:
{SEPARATOR_LINE}
{{relationship_types}}
{SEPARATOR_LINE}
""".strip()


DR_DECISION_PROMPT = f"""
You need to route a user query request to the appropriate tool.

You have two tools available, "SEARCH" and "KNOWLEDGE_GRAPH".

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
 to see whether the question can be answered by the KNOWLEDGE_GRAPH tool at all. If not, use 'SEARCH'.
 - if the question can be answered by the KNOWLEDGE_GRAPH tool, but the question seems like a standard \
 'search for this'-type of question, then also use 'SEARCH'.
 - also consider whether the user query implies whether a standard search query should be used or a \
knowledge graph query. For example, 'use a simple search to find <xyz>' would refer to a standard search query, \
whereas 'use the knowledge graph (or KG) to summarize...' should be a knowledge graph query.


Please answer ONLY with 'SEARCH' or 'KNOWLEDGE_GRAPH'.

ANSWER:

"""
