from onyx.configs.kg_configs import KG_OWN_COMPANY

# Standards
SEPARATOR_LINE = "-------"
SEPARATOR_LINE_LONG = "---------------"
NO_EXTRACTION = "No extraction of knowledge graph objects was feasable."
YES = "yes"
NO = "no"

# Framing/Support/Template Prompts
ENTITY_TYPE_SETTING_PROMPT = f"""
Here are the entity types that are available for extraction. Please only extract entities \
of these types (or 'any' object of a type, indicated by a '*').
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

EXTRACTION_FORMATTING_PROMPT = r"""
{{"entities": [<a list of entities of the prescripted entity types that you can reliably identify in the text, \
formatted as '<ENTITY_TYPE_NAME>:<entity_name>' (please use that capitalization). If allowed options \
are provided above, you can only extract those types of entities! Again, there should be an 'Other' \
option. Pick this if non of the others apply.>],
"relationships": [<a list of relationship between the identified entities, formatted as \
'<SOURCE_ENTITY_TYPE_NAME>:<source_entity_name>__<one of three options: 'relates_positively_to', \
'relates_negatively_to', or 'relates_neutrally_to'. Pick the most appropriate option based on the \
relationship between the entities implied by the text. 'relates_neutrally_to' should generally be \
chosen if in doubt, or if the proper term may be 'interested_in', 'has', 'uses', 'wants', etc. \
Pick 'relates_positively_to', or 'relates_negatively_to' only of it is clear. The positive option \
could for example apply of something is now solved, value was delievered, a sales was made, someone \
is happy, etc. The negative option would apply of a problem is reported, someone is unhappy, etc.>\
__<TARGET_ENTITY_TYPE_NAME>:<target_entity_name>'>],
"terms": [<a comma-separated list of high-level terms (each one one or two words) that you can reliably \
identify in the text, each formatted simply as '<term>'>]
}}
""".strip()

QUERY_ENTITY_EXTRACTION_FORMATTING_PROMPT = r"""
{{"entities": [<a list of entities of the prescripted entity types that you can reliably identify in the text, \
formatted as '<ENTITY_TYPE_NAME>:<entity_name>' (please use that capitalization)>],
"terms": [<a comma-separated list of high-level terms (each one one or two words) that you can reliably \
identify in the text, each formatted simply as '<term>'>],
"time_filter": <if needed, a SQL-like filter for a field called 'event_date'. Do not select anything here \
unless you are sure that the questions asks for that filter. Only apply a time_filter if the question explicitly \
mentions a specific date, time period, or event that can be directly translated into a date filter. Do not assume \
the current date, if given, as the event date or to imply that the should be a filter. Do not make assumptions here \
but only use the information provided to infer whether there should be a time_filter, and if so, what it should be.>
}}
""".strip()

QUERY_RELATIONSHIP_EXTRACTION_FORMATTING_PROMPT = r"""
{{"relationships": [<a list of relationship between the identified entities, formatted as \
'<SOURCE_ENTITY_TYPE_NAME>:<source_entity_name>__<one of three options: 'relates_positively_to', \
'relates_negatively_to', or 'relates_neutrally_to'. Pick the most appropriate option based on the \
relationship between the entities implied by the text. 'relates_neutrally_to' should generally be \
chosen if in doubt, or if the proper term may be 'interested_in', 'has', 'uses', 'wants', etc. \
Pick 'relates_positively_to', or 'relates_negatively_to' only of it is clear. The positive option \
could for example apply of something is now solved, value was delievered, a sales was made, someone \
is happy, etc. The negative option would apply of a problem is reported, someone is unhappy, etc. \
If the 'natural' relationship is of a very different nature (like: 'participated_in', choose \
'relates_neutrally_to'. It is MOST IMPORTANT THAT THE RELATIONSHIP IS BETWEEN THE TWO ENTITIES \
IS CAPTURED, the type is less important. But again, if in doubt, pick 'relates_neutrally_to'.\
__<TARGET_ENTITY_TYPE_NAME>:<target_entity_name>'>]
}}
""".strip()

EXAMPLE_1 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:*"],
    "relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:*"], "terms": []}}
""".strip()

EXAMPLE_2 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:performance"],
    "relationships": ["ACCOUNT:*__relates_negatively_to__CONCERN:performance"], "terms": ["performance issue"]}}
""".strip()

EXAMPLE_3 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:performance", "CONCERN:user_experience"],
    "relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:performance",
                      "ACCOUNT:Nike__relates_positively_to__CONCERN:user_experience"],
    "terms": ["performance", "user experience"]}}
""".strip()

EXAMPLE_4 = r"""
{{"entities": ["ACCOUNT:Nike", "FEATURE:dashboard", "CONCERN:performance"],
    "relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:performance",
                      "ACCOUNT:Nike__relates_negatively_to__FEATURE:dashboard",
                      "ACCOUNT:NIKE__relates_positively_to__FEATURE:dashboard"],
    "terms": ["value", "performance"]}}
""".strip()

RELATIONSHIP_EXAMPLE_1 = r"""
'Which issues did Nike report?' and the extracted entities were found to be:

  "ACCOUNT:Nike", "CONCERN:*"

then a valid relationship extraction could be:

{{"relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:*"]}}
""".strip()

RELATIONSHIP_EXAMPLE_2 = r"""
'Did Nike say anything about performance issues?' and the extracted entities were found to be:

"ACCOUNT:Nike", "CONCERN:performance"

then a much more suitable relationship extraction could be:

{{"relationships": ["ACCOUNT:*__relates_negatively_to__CONCERN:performance"]}}
""".strip()

RELATIONSHIP_EXAMPLE_3 = r"""
'Did Nike report some performance issues with our solution? And were they happy that the user experience issue got solved?', \
and the extracted entities were found to be:

"ACCOUNT:Nike", "CONCERN:performance", "CONCERN:user_experience"

then a valid relationship extraction could be:

{{"relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:performance",
                      "ACCOUNT:Nike__relates_positively_to__CONCERN:user_experience"]}}
""".strip()

RELATIONSHIP_EXAMPLE_4 = r"""
'Nike reported some performance issues with our dashboard solution, but do they think it delivers great value nevertheless?' \
and the extracted entities were found to be:

"ACCOUNT:Nike", "FEATURE:dashboard", "CONCERN:performance"

then a valid relationship extraction could be:
Example 4:

{{"relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:performance",
                      "ACCOUNT:Nike__relates_negatively_to__FEATURE:dashboard",
                      "ACCOUNT:NIKE__relates_positively_to__FEATURE:dashboard"]}}

Explanation:
 - Nike did report performance concerns
 - Nike had problems with the dashboard, which is a feature
 - We are interested in the value relationship between Nike and the dashboard feature

""".strip()

RELATIONSHIP_EXAMPLE_5 = r"""
'In which emails did Nike discuss their issues with the dahboard?' \
and the extracted entities were found to be:

"ACCOUNT:Nike", "FEATURE:dashboard", "EMAIL:*"

then a valid relationship extraction could be:

{{"relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:*",
                      "ACCOUNT:Nike__relates_negatively_to__FEATURE:dashboard",
                      "ACCOUNT:NIKE__relates_neutrally_to__EMAIL:*",
                      "EMAIL:*__relates_neutrally_to__FEATURE:dashboard",
                      "EMAIL:*__relates_negatively_to__CONCERN:* "]}}
Explanation:
 - Nike did report unspecified concerns
 - Nike had problems with the dashboard, which is a feature
 - We are interested in emails that Nike excchanged with us
""".strip()

RELATIONSHIP_EXAMPLE_6 = r"""
'List the last 5 emails that Lisa exchamged with Nike:' \
and the extracted entities were found to be:

"ACCOUNT:Nike", "EMAIL:*", "EMPLOYEE:Lisa"

then a valid relationship extraction could be:

{{"relationships": ["ACCOUNT:Nike__relates_negatively_to__CONCERN:*",
                      "ACCOUNT:Nike__relates_negatively_to__FEATURE:dashboard",
                      "ACCOUNT:NIKE__relates_neutrally_to__EMAIL:*"]}}
Explanation:
 - Nike did report unspecified concerns
 - Nike had problems with the dashboard, which is a feature
 - We are interested in emails that Nike excchanged with us
""".strip()


ENTITY_EXAMPLE_1 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:*"], "terms": []}}
""".strip()

ENTITY_EXAMPLE_2 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:performance"], "terms": ["performance issue"]}}
""".strip()

MASTER_EXTRACTION_PROMPT = f"""
You are an expert in the area of knowledge extraction in order to construct a knowledge graph. You are given a text \
and asked to extract entities, relationships, and terms from it that you can reliably identify.

Here are the entity types that are available for extraction. Some of them may have a description, others \
should be obvious. Also, for a given entity allowed options may be provided. If allowed options are provided, \
you can only extract those types of entities! If no allowed options are provided, take your best guess.


You can ONLY extract entities of these types and relationships between objects of these types:
{SEPARATOR_LINE}
{ENTITY_TYPE_SETTING_PROMPT}
{SEPARATOR_LINE}
Please format your answer in this format:
{SEPARATOR_LINE}
{EXTRACTION_FORMATTING_PROMPT}
{SEPARATOR_LINE}

The list above here is the exclusive, only list of entities you can chose from!

Here are some important additional instructions. (For the purpose of illustration, assume that ]
 "ACCOUNT", "CONCERN", and "FEATURE" are all in the list of entity types above, and shown actual \
entities fall into allowed options. Note that this \
is just assumed for these examples, but you MUST use only the entities above for the actual extraction!)

- You can either extract specific entities if a specific entity is referred to, or you can refer to the entity type.
* if the entity type is referred to in general, you would use '*' as the entity name in the extraction.
As an example, if the text would say:
 'Nike reported that they had issues'
then a valid extraction could be:
Example 1:
{EXAMPLE_1}

* If on the other hand the text would say:
'Nike reported that they had performance issues'
then a much more suitable extraction could be:
Example 2:
{EXAMPLE_2}

- You can extract multiple relationships between the same two entity types.
As an example, if the text would say:
'Nike reported some performance issues with our solution, but they are very happy that the user experience issue got solved.'
then a valid extraction could be:
Example 3:
{EXAMPLE_3}

- You can extract multiple relationships between the same two actual entities if you think that \
there are multiple relationships between them based on the text.
As an example, if the text would say:
'Nike reported some performance issues with our dashboard solution, but they think it delivers great value.'
then a valid extraction could be:
Example 4:
{EXAMPLE_4}

Note that effectively a three-way relationship (Nike - performance issues - dashboard) extracted as two individual \
relationships.

- Again,
   -  you should only extract entities belinging to the entity types above - but do extract all that you \
can reliably identify in the text
   - use refer to 'all' entities in an entity type listed above by using '*' as the entity name
   - only extract important relationships that signify something non-trivial, expressing things like \
needs, wants, likes, dislikes, plans, interests, lack of interests, problems the account is having, etc.
   - you MUST only use the intiali list of entities provided! Ignore the entities in the examples unless \
the are also part of the initial list of entities! This is essential!
   - only extract relationships between the entities extracted first!


{SEPARATOR_LINE}

Here is the text you are asked to extract knowledge from:
{SEPARATOR_LINE}
---content---
{SEPARATOR_LINE}
""".strip()


QUERY_ENTITY_EXTRACTION_PROMPT = f"""
You are an expert in the area of knowledge extraction and using knowledge graphs. You are given a question \
and asked to extract entities and terms from it that you can reliably identify and that then \
can later be matched with a known knowledge graph. You are also asked to extract time filters SHOULD \
there be an explicit mention of a date or time frame in the QUESTION (note: last, first, etc.. DO NOT \
imply the need for a time filter just because the question asks for something that is not the current date. \
The will relate to ordering that we will handle separately).

Today is ---today_date---, which may or may not be relevant.
Here are the entity types that are available for extraction. Some of them may have \
a description, others should be obvious. You can ONLY extract entities of these types:
{SEPARATOR_LINE}
{ENTITY_TYPE_SETTING_PROMPT}
{SEPARATOR_LINE}

The list above here is the exclusive, only list of entities you can chose from!

Also, note that there are fixed relationship types between these entities. Please consider those \
as well so to make sure that you are not missing implicit entities! Implicit entities are often \
in verbs ('emailed to', 'talked to', ...). Also, they may be used to connect entities that are \
clearly in the question.

{SEPARATOR_LINE}
{RELATIONSHIP_TYPE_SETTING_PROMPT}
{SEPARATOR_LINE}

Here are some important additional instructions. (For the purpose of illustration, assume that \
 "ACCOUNT", "CONCERN", "EMAIL", and "FEATURE" are all in the list of entity types above. Note that this \
is just assumed for these examples, but you MUST use only the entities above for the actual extraction!)

- You can either extract specific entities if a specific entity is referred to, or you can refer to the entity type.
* if the entity type is referred to in general, you would use '*' as the entity name in the extraction.
As an example, if the question would say:
 'Which issues did Nike report?'
then a valid entity and term extraction could be:
Example 1:
{ENTITY_EXAMPLE_1}

* If on the other hand the question would say:
'Did Nike say anything about performance issues?'
then a much more suitable entity and term extraction could be:
Example 2:
{ENTITY_EXAMPLE_2}

- Again,
   -  you should only extract entities belonging to the entity types above - but do extract all that you \
can reliably identify in the text
   - use refer to 'all' entities in an entity type listed above by using '*' as the entity name
   - keep the terms high-level
   - similarly, if a specific entity type is referred to in general, you should use '*' as the entity name
   - you MUST only use the intial list of entities provided! Ignore the entities in the examples unless \
the are also part of the initial list of entities! This is essential!
   - don't forget to provide answers also to the event filtering and whether documents need to be inspected!

{SEPARATOR_LINE}

Here is the question you are asked to extract desired entities and terms from:
{SEPARATOR_LINE}
---content---
{SEPARATOR_LINE}

Please format your answer in this format:
{SEPARATOR_LINE}
{QUERY_ENTITY_EXTRACTION_FORMATTING_PROMPT}
{SEPARATOR_LINE}

""".strip()


QUERY_RELATIONSHIP_EXTRACTION_PROMPT = f"""
You are an expert in the area of knowledge extraction and using knowledge graphs. You are given a question \
and previously you were asked to identify known entities in the question. Now you are asked to extract \
the relationships between the entities you have identified earlier.

First off as background, here are the entity types that are known to the system:
{SEPARATOR_LINE}
---entity_types---
{SEPARATOR_LINE}


Here are the entities you have identified earlier:
{SEPARATOR_LINE}
---identified_entities---
{SEPARATOR_LINE}

Note that the notation for the entities is <ENTITY_TYPE>:<ENTITY_NAME>.

Here are the options for the relationship types(!) between the entities you have identified earlier:
{SEPARATOR_LINE}
---relationship_type_options---
{SEPARATOR_LINE}

These types are formated as <SOURCE_ENTITY_TYPE>__<RELATIONSHIP_SHORTHAND>__<TARGET_ENTITY_TYPE>, and they \
limit the allowed relationships that you can extract. You would then though use the actual full entities as in:

<SOURCE_ENTITY_TYPE>:<SOURCE_ENTITY_NAME>__<RELATIONSHIP_SHORTHAND>__<TARGET_ENTITY_TYPE>:<TARGET_ENTITY_NAME>.

NOTE: <RELATIONSHIP_SHORTHAND> can only take one of three values: 'relates_neutrally_to', 'relates_positively_to', \
or 'relates_negatively_to'. Pick the most appropriate option based on the \
relationship between the entities implied by the question. 'relates_neutrally_to' should generally be \
chosen if in doubt, or if the proper term may be 'interested_in', 'has', 'uses', 'wants', etc. \
Pick 'relates_positively_to', or 'relates_negatively_to' only of it is clear. The positive option \
could for example apply of something is now solved, value was delievered, a sales was made, someone \
is happy, etc. The negative option would apply of a problem is reported, someone is unhappy, etc.

Please format your answer in this format:
{SEPARATOR_LINE}
{QUERY_RELATIONSHIP_EXTRACTION_FORMATTING_PROMPT}
{SEPARATOR_LINE}

The list above here is the exclusive, only list of entities and relationship types you can chose from!

Here are some important additional instructions. (For the purpose of illustration, assume that ]
 "ACCOUNT", "CONCERN", and "FEATURE" are all in the list of entity types above. Note that this \
is just assumed for these examples, but you MUST use only the entities above for the actual extraction!)

- You can either extract specific entities if a specific entity is referred to, or you can refer to the entity type.
* if the entity type is referred to in general, you would use '*' as the entity name in the extraction.

As an example, if the question would say:

{RELATIONSHIP_EXAMPLE_1}

* If on the other hand the question would say:

{RELATIONSHIP_EXAMPLE_2}

- You can extract multiple relationships between the same two entity types.
For example 3, if the question would say:

{RELATIONSHIP_EXAMPLE_3}

- You can extract multiple relationships between the same two actual entities if you think that \
there are multiple relationships between them based on the question.
As an example, if the question would say:

{RELATIONSHIP_EXAMPLE_4}

Note that effectively a three-way relationship (Nike - performance issues - dashboard) extracted as two individual \
relationships.

- Again,
   - you can only extract relationships between the entities extracted earlier
   - you can only extract the relationships that match the listed relationship types
   - if in doubt and there are multiple relationships between the same two entities, you can extract \
all of those that may fit with the question.
   - be really think through the question which type of relationships should be extracted and which should not.

{SEPARATOR_LINE}

Here is the question you are asked to extract desired entities, relationships, and terms from:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}
""".strip()


### Source-specific prompts

FIREFLIES_CHUNK_PREPROCESSING_PROMPT = f"""
This is a call between employees of the VENDOR's company and representatives of one or more ACCOUNTs (usually one). \
When you exract information based on the instructions, please make sure that you properly attribute the information \
to the correct employee and account. \

Here are the participants (name component of emil) from us ({KG_OWN_COMPANY}):
{{participant_string}}

Here are the participants (name component of emil) from the other account(s):
{{account_participant_string}}

In the text it should be easy to associate a name with the email, and then with the account ('us' vs 'them'). If in doubt, \
look at the context and try to identify whether the statement comes from the other account. If you are not sure, ignore.

Note: when you extract relationships, please make sure that:
  - if you see a relationship for one of our employees, you should extract the relationship once for the employee AND \
    once for the account, i.e. VENDOR:{KG_OWN_COMPANY}.
  - if you see a relationship for one of the representatives of other accounts, you should extract the relationship \
only for the account!

--
And here is the content:
{{content}}
""".strip()


FIREFLIES_DOCUMENT_CLASSIFICATION_PROMPT = f"""
This is the beginning of a call between employees of the VENDOR's company ({KG_OWN_COMPANY}) and other participants.

Your task is to classify the call into one of the following categories:
{{category_options}}

Please also consider the participants when you perform your classification task - they can be important indicators \
for the category.

Please format your answer as a string in the format:

REASONING: <your reasoning for the classification> - CATEGORY: <the category you have chosen. Only use {{category_list}}>

--
And here is the beginning of the call, including title and participants:

{{beginning_of_call_content}}
""".strip()


STRATEGY_GENERATION_PROMPT = f"""
Now you need to decide what type of strategy to use to answer a given question, how ultimately \
the answer should be formatted to match the users expectation, and what an appropriate question \
to 'one object (or one set of objects)' may be, should the answer logicaly benefit from a divide \
and conquer strategy, or it naturally relates to one or few individual objects. Also, you are \
supposed whether a divide and conquer strategy would be appropriate.

Here are more instructions:

a) Regarding the strategy: there are two types of strategies available to you:

1. SIMPLE: You think you can awnswer the question using a atabase that is aware of the entities, relationships, \
and terms, and is generally suitable if it is enough to either list or count entities or relationships. Usually, \
'SIMPLE' is chosen for questions of the form 'how many...' (always), or 'list the...' (often).
2. DEEP: You think you really should ALSO leverage the actual text of sources to answer the question, which sits \
in a vector database.

Your task is to decide which of the two strategies to use.

b) Regarding the format of the answer: there are also two types of formats available to you:

1. LIST: The user would expect an answer should be a bullet point list of objects with text associated with each \
bullet points (or sub-bullets) likely having some text associated with it. This will be clearer once the data is available.
2. TEXT: The user would expect the questions to be answered in text form.

Your task is to decide which of the two formats to use.


c) Regarding the broken down question for one object:

Always generate a broken_down_question if the question pertains ultimately to a specific objects, even if it seems to be \
a singular object.

- If the question is of type 'how many...', or similar, then imagine that the individual objects have been \
found and you want to ask each object something that illustrates why/in what what that objecft relates to the \
question. (question: 'How many cars are fast?' -> broken_down_question: 'How fast is this car?')

- Assume the answer would either i) best be generated by first analyzing one object at a time, then aggregating \
the results, or ii) directly relates to one or few objects found through matching suitable criteria.

- The key is to drop any filtering/criteria matching as the objects are already filtered by the criteria. Also, do not \
try to verify here whether the object in question actually satisfies a filter criteria, but rather see \
what it says/does etc. In other words, use this to identify more details about the object, as it relates \
to the original question.
(Example: question: 'What did our oil & gas customers say about the new product?' -> broken_down_question: \
'What did this customer say about the new product?',
or:
question: 'What was in the email from Frank?' -> broken_down_question: 'What is in this email?')


d) Regarding the divide and conquer strategy:

You are supposed to decide whether a divide and conquer strategy would be appropriate. That means, do you think \
that in order to answer the question, it would be good to first analyze one object at a time, and then aggregate the \
results? Or should the information rather be analyzed as a whole? This would be 'yes' or 'no'.





To help you, here are the entities, relationships, and terms that you have extracted:
{SEPARATOR_LINE}
---entities---
---relationships---
---entities---
{SEPARATOR_LINE}

Here is the question you are asked to answer:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

Please answer in json format in this form:

{{
    "strategy": <answer with "DEEP" or "SIMPLE">,
    "format": <answer with "LIST" or "TEXT">,
    "broken_down_question": <the question that can be used to analyze one object at a time (or 'the object' that \
fits all criteria), or an empty string if the answer should not be generated by analyzing one object at a time>,
"divide_and_conquer": <answer with "yes" or "no">
}}

Do not include any other text or explanations.

"""


SIMPLE_SQL_PROMPT = f"""
You are an expert in generating a SQL statement that only uses two tables, one for entities and another for relationships \
between two entities - to find (or count) the desired entities.

Here is the structure of the two tables:
{SEPARATOR_LINE}
Entities:
 - Table name: kg_entity
 - Columns:
   - id_name: the id of the entity, compining the entity type and the name [example: ACCOUNT:Nike]
   - name: the name of the entity [example: Nike]
   - entity_type_id_name: the type of the entity [example: ACCOUNT]
   - event_time: the timestamp of the event [example: 2021-01-01 00:00:00]


Relationships:
 - Table name: kg_relationship
 - Columns:
   - id_name: the id of the relationship, compining the relationship type and the names of the entities \
[example: ACCOUNT:Nike__had__CONCERN:performance]
   - type: the type of the relationship [example: had]
   - source_node: the id_name of the first entity in the relationship, foreign key to kg_entity.id_name \
[example: ACCOUNT:Nike]
   - target_node: the id_name of the second entity in the relationship, foreign key to kg_entity.id_name \
[example: CONCERN:performance]

{SEPARATOR_LINE}

Importantly, here are the entity types that you can use, with a short description what they mean. You may need to \
identify the proper entity type through its description.

{SEPARATOR_LINE}
---entity_types---
{SEPARATOR_LINE}


Here is the question you are supposed to translate into a SQL statement:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

We already have identified the entities and  relationships that the SQL statement likely *should* use (but note the \
exception below!):
{SEPARATOR_LINE}
Query entities (id_name):
---query_entities---

--

Query relationships (id_name):
---query_relationships---

{SEPARATOR_LINE}

EXCEPTIONS:
  - if you see an *entity* of the form <entity_type>:* in the entities or the relationships, you should use \
the entity type, not the entity itself, appropriately in the SQL statement!! These refer effectively to \
'any entity of type <entity_type>', and it is not an actual entity!
  - DO NOT include entities of the type <entity>:* in counts or lists! These are not actual entities but \
rather refer to any entity of that type!


Note:
- The id_name of each enity has the format <entity_type_id_name>:<name>, where 'entity_type_id_name' and 'name' are columns and \
  the values <entity_type_id_name> and <name> can be used for filtering.
- The id_name of each relationship has the format \
<relationship_type_id_name>:<source_entity_id_name>__<relationship_type>__<target_entity_id_name>, where \
we can also, if needed, get values from for filtering by type or by name if needed.
- Please generate a SQL statement that uses only the entities and relationships, implied types and names, and things \
like (*) if you want to produce a count(*), etc, and obviously the tables.
- If you see in the used entities items like '<entity_type>:*', that refers to any of those entities. \
Example: if you see 'ACCOUNT:*', that means you can use any account. So if you are supposed to count the 'ACCOUNT:*', \
you should count the entities of entity_type_id_name 'ACCOUNT'.
- The entity table can only be joined on the relationshiptable which can then be joined again on the entity table, etc.
- Ultimately this should be a select statement that asks about entities, or a select count() of entities.
- You can ultimately only return i) numbers (if counts are asked), or ii) entity id_names. Particularly, do not return names.
- Try to be as efficient as possible.
- for actual counts or lists DO NOT include entities of the type <entity>:*! These are not actual entities but \
rather refer to any entity of that type!
- the SQL statement MUST ultimately only return entities (by id_name), or aggregations (count, avg, max, min, etc.). \
DO NOT compose a SQL statement that returns relationships.
- in the response, do not include entities that end on ':*', as these are not actual entities but rather refer to any entity \
so the final list should have a filter of type .... 'where <>. of that type!


Approach:
Please think through this step by step. Then, when you have it say 'SQL:' followed ONLY by the SQL statement. The SQL statement \
must end with a ';'


Your answer:

"""


SQL_AGGREGATION_REMOVAL_PROMPT = f"""
You are a SQL expert. You were provided with a SQL statement that returns an aggregation, and you are \
tasked to show the underlying objects that were aggregated. For this you need to remove the aggregate functions \
from the SQL statement in the correct way.

Additional rules:
 - if you see a 'select count(*)', you should NOT convert \
that to 'select *...', but rather return the corresponding id_name, entity_type_id_name, name, and document_id.  \
As in: 'select <table, if necessary>.id_name, <table, if necessary>.entity_type_id_name, \
<table, if necessary>.name, <table, if necessary>.document_id ...'. \
The id_name is always the primary index, and those should be returned, along with the type (entity_type_id_name), \
the name (name) of the objects, and the document_id (document_id) of the object.
- Add a limit of 30 to the select statement.
- Don't change anything else.
- The final select statement needs obviously to be a valid SQL statement.

Here is the SQL statement you are supposed to remove the aggregate functions from:
{SEPARATOR_LINE}
---sql_statement---
{SEPARATOR_LINE}

Please answer in the following text format:

<short reasoning> SQL: <the SQL statement without the aggregate functions>
""".strip()

SEARCH_FILTER_CONSTRUCTION_PROMPT = f"""
You need to prepare a search across text segments that contain the information necessary to \
answer a question. The text segments have tags that can be used to filter for the relevant segments. \

Your task is to find the filters that are needed to find the relevant segments from a list of \
options. Filters can be entities or relationships. Selected text filters are required \
to be tagged with the entity and relationship filters you select.

Here are the options you have:
{SEPARATOR_LINE}
Entity filters:

---entity_filters---

{SEPARATOR_LINE}
Relationship filters:

---relationship_filters---

{SEPARATOR_LINE}

Note that entity filters are of the form <entity_type>:<entity_name>, and relationship filters are of the form \
<source_entity_type>:<source_entity_name>__<relationship_type>__<target_entity_type>:<target_entity_name>.

It is useful to understand what the entity types represent:
{SEPARATOR_LINE}

---entity_type_descriptions---

{SEPARATOR_LINE}

Also - for your information - the following SQL statement was generated to help find our count \
relevant objects:
{SEPARATOR_LINE}
---sql_query---
{SEPARATOR_LINE}

Finally, here is the question you are supposed to answer:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

Again, your task is to select the filters that are implied by the question, and that therefore \
should be used to filter the text segments.

Please answer in the following json dictionary format:

{{
    "entity_filters": <a list of entity filters>,
    "relationship_filters": <a list of relationship filters>
}}
""".strip()


OUTPUT_FORMAT_NO_EXAMPLES_PROMPT = f"""
You need to format an answer to a research question. \
You will see what the desired output is, the original question, and the answer to the research question. \
Your purpose is to generate the answer respecting the desired format.

Notes:
 - Note that you are a language model and that answers may or may not be perfect. To communicate \
this to the user, consider phrases like 'I found [10 accounts]...', or 'Here are a number of [goals] that \
I found...]
- Please DO NOT mention the explicit output format in your answer. Just use it to inform the formatting.

Here is the unformatted answer to the research question:
{SEPARATOR_LINE}
---introductory_answer---
{SEPARATOR_LINE}

Here is the original question:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

And finally, here is the desired output format:
{SEPARATOR_LINE}
---output_format---
{SEPARATOR_LINE}

Please start generating the answer, without any explanation. There should be no real modifications to \
the text, after all, all you need to do here is formatting. \

Your Answer:
""".strip()


OUTPUT_FORMAT_PROMPT = f"""
You need to format the answers to a research question that targeted one or more objects. \
An overall introductory answer may be provided to you, as well as the research results for each individual object. \
You will also be provided with the original question as background, and the desired format. \

Your purpose is to generate a consolidated and FORMATTED answer that starts of with the introductory \
answer, and then formats the research results for each individual object in the desired format. \
Do not add any other text please!

Notes:
 - Note that you are a language model and that answers may or may not be perfect. To communicate \
this to the user, consider phrases like 'I found [10 accounts]...', or 'Here are a number of [goals] that \
I found...]
- Please DO NOT mention the explicit output format in your answer. Just use it to inform the formatting.
- DO NOT add any content to the introductory answer!


Here is the original question for your background:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

Here is the desired output format:
{SEPARATOR_LINE}
---output_format---
{SEPARATOR_LINE}

Here is the introductory answer:
{SEPARATOR_LINE}
---introductory_answer---
{SEPARATOR_LINE}

Here are the research results that you should - respecting the target format- return in a formatted way:
{SEPARATOR_LINE}
---research_results---
{SEPARATOR_LINE}

Please start generating the answer, without any explanation. After all, all you need to do here is formatting. \


Your Answer:
""".strip()


OUTPUT_FORMAT_NO_OVERALL_ANSWER_PROMPT = f"""
You need to format the return of research on multiple objects. The research results will be given \
to you as a string. You will also see what the desired output is, as well as the original question. \
Your purpose is to generate the answer respecting the desired format.

Notes:
 - Note that you are a language model and that answers may or may not be perfect. To communicate \
this to the user, consider phrases like 'I found [10 accounts]...', or 'Here are a number of [goals] that \
I found...]
- Please DO NOT mention the explicit output format in your answer. Just use it to inform the formatting.
 - Often, you are also provided with a list of explicit examples. If  - AND ONLY IF - the list is not \
empty, then these should be listed at the end with the text:
'...
Here are some examples of what I found:
<bullet point list of examples>
...'
 - Again if the list of examples is and empty string then skip this section! Do not use the \
results data for this purpose instead! (They will already be handled in the answer.)
- Even if the desired output format is 'text', make sure that you keep the individual research results \
separated by bullet points, and mention the object name first, followed by a new line. The object name \
is at the beginning of the research result, and should be in the format <object_type>:<object_name>.


Here is the original question:
{SEPARATOR_LINE}
---question---
{SEPARATOR_LINE}

And finally, here is the desired output format:
{SEPARATOR_LINE}
---output_format---
{SEPARATOR_LINE}

Here are the research results that you should properly format:
{SEPARATOR_LINE}
---research_results---
{SEPARATOR_LINE}

Please start generating the answer, without any explanation. After all, all you need to do here is formatting. \


Your Answer:
""".strip()


KG_OBJECT_SOURCE_RESEARCH_PROMPT = f"""
You are an expert in extracting relevant structured information from a list of documents that \
should relate to one object. You are presented with a list of documemnts that have been determined to be \
relevant the task of interest. Your goal is to extract the information asked around these topics:
You should look at the documents - in no particular order! - and extract the information that relates \
to a question:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Here are the documents you are supposed to search through:
--
{{document_text}}
{SEPARATOR_LINE}
Note: please cite your sources inline as you generate the results! Use the format [[1]](), etc. Infer the \
number from the provided context documents. This is very important!

Please now generate the answer to the question given the documents:
""".strip()


####################

DC_OBJECT_NO_BASE_DATA_EXTRACTION_PROMPT = f"""
You are an expert in finding relevant objects/objext specifications of the same type in a list of documents. \
In this case you are interested \
in generating: {{objects_of_interest}}.
You should look at the documents - in no particular order! - and extract each object you find in the documents.
{SEPARATOR_LINE}
Here are the documents you are supposed to search through:
--
{{document_text}}
{SEPARATOR_LINE}

Here is the task you are asked to find the objects of type for, which should
{SEPARATOR_LINE}
{{task}}
{SEPARATOR_LINE}

Here is the question that provides critical context for the task:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please answer the question in the following format:

REASONING: <your reasoning for the classification> - OBJECTS: <the objects - just their names - that you found, \
separated by ';'>

""".strip()


DC_OBJECT_WITH_BASE_DATA_EXTRACTION_PROMPT = f"""
You are an expert in finding relevant objects/objext specifications of the same type in a list of documents. \
In this case you are interested \
in generating: {{objects_of_interest}}.
You should look at the provided data - in no particular order! - and extract each object you find in the documents.
{SEPARATOR_LINE}
Here are the data provided by the user:
--
{{base_data}}
{SEPARATOR_LINE}

Here is the task you are asked to find the objects of type for, which should
{SEPARATOR_LINE}
{{task}}
{SEPARATOR_LINE}

Here is the request that provides critical context for the task:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Please address the request in the following format:

REASONING: <your reasoning for the classification> - OBJECTS: <the objects - just their names - that you found, \
separated by ';'>

""".strip()


DC_OBJECT_SOURCE_RESEARCH_PROMPT = f"""
You are an expert in extracting relevant structured information for in a list of documents that should relate to one \
object.
You should look at the documents - in no particular order! - and extract the information asked for this task:
{SEPARATOR_LINE}
{{task}}
{SEPARATOR_LINE}

Here are the documents you are supposed to search through:
--
{{document_text}}
{SEPARATOR_LINE}

Note: please cite your sources inline as you generate the results! Use the format [1], etc. Infer the \
number from the provided context documents. This is very important!

Please address the task in the following format:

REASONING:
<your reasoning for the classification>
RESEARCH RESULTS:
{{format}}

""".strip()


DC_OBJECT_CONSOLIDATION_PROMPT = f"""
You are a helpful assistant that consolidates information about a specific object \
from multiple sources.
The object is:
{SEPARATOR_LINE}
{{object}}
{SEPARATOR_LINE}
and the information is
{SEPARATOR_LINE}
{{information}}
{SEPARATOR_LINE}

Please consolidate the information into a single, concise answer. The consolidated informtation \
for the object should be in the following format:
{SEPARATOR_LINE}
{{format}}
{SEPARATOR_LINE}

Overall, please use this structure to communicate the consolidated information:
{SEPARATOR_LINE}

REASONING: <your reasoning for consolidating the information>
INFORMATION:
<consolidated information in the proper format that you have created>
"""


DC_FORMATTING_WITH_BASE_DATA_PROMPT = f"""
You are an expert in text formatting. Your task is to take a given text and convert it 100 percent accurately \
in a new format.
Here is the text you are supposed to format:
{SEPARATOR_LINE}
{{text}}
{SEPARATOR_LINE}

Here is the format you are supposed to use:
{SEPARATOR_LINE}
{{format}}
{SEPARATOR_LINE}

Please start the generation directly with the formatted text.
"""

DC_FORMATTING_NO_BASE_DATA_PROMPT = f"""
You are an expert in text formatting. Your task is to take a given text and the initial \
data provided by the user, and convert it 100 percent accurately \
in a new format. The base data may also contain important relationships that are critical \
for the formatting.

Here is the initial data provided by the user:
{SEPARATOR_LINE}
{{base_data}}
{SEPARATOR_LINE}

Here is the text you are supposed combine (and format) with the initial data, adhering to the \
format instructions provided by later in the prompt:
{SEPARATOR_LINE}
{{text}}
{SEPARATOR_LINE}

And here are the format instructions you are supposed to use:
{SEPARATOR_LINE}
{{format}}
{SEPARATOR_LINE}

Please start the generation directly with the formatted text.
"""
