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
of these types and relationships between objects of these types (or 'any' object of a type).
{SEPARATOR_LINE}
{{entity_types}}
{SEPARATOR_LINE}
""".strip()


EXTRACTION_FORMATTING_PROMPT = r"""
{{"entities": [<a list of entities of the prescripted entity types that you can reliably identify in the text, \
formatted as '<ENTITY_TYPE_NAME>:<entity_name>' (please use that capitalization)>],
"relationships": [<a list of relationship between the identified entities, formatted as \
'<SOURCE_ENTITY_TYPE_NAME>:<source_entity_name>__<a word or two that captures the nature \
of the relationship (if appropriate, inlude a judgement, as in 'likes' or 'dislikes' vs. 'uses', etc.)>\
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
"time_filter": <if needed, a SQL_like filter for a field called 'event_date'>
}}
""".strip()

QUERY_RELATIONSHIP_EXTRACTION_FORMATTING_PROMPT = r"""
{{"relationships": [<a list of relationship between the identified entities, formatted as \
'<SOURCE_ENTITY_TYPE_NAME>:<source_entity_name>__<a word or two that captures the nature \
of the relationship (if appropriate, inlude a judgement, as in 'likes' or 'dislikes' vs. 'uses', etc.)>\
__<TARGET_ENTITY_TYPE_NAME>:<target_entity_name>'>]
}}
""".strip()

EXAMPLE_1 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:*"],
    "relationships": ["ACCOUNT:Nike__had__CONCERN:*"], "terms": []}}
""".strip()

EXAMPLE_2 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:performance"],
    "relationships": ["ACCOUNT:*__had_issues__CONCERN:performance"], "terms": ["performance issue"]}}
""".strip()

EXAMPLE_3 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:performance", "CONCERN:user_experience"],
    "relationships": ["ACCOUNT:Nike__had__CONCERN:performance",
                      "ACCOUNT:Nike__solved__CONCERN:user_experience"],
    "terms": ["performance", "user experience"]}}
""".strip()

EXAMPLE_4 = r"""
{{"entities": ["ACCOUNT:Nike", "FEATURE:dashboard", "CONCERN:performance"],
    "relationships": ["ACCOUNT:Nike__had__CONCERN:performance",
                      "ACCOUNT:Nike__had_issues__FEATURE:dashboard",
                      "ACCOUNT:NIKE__gets_value_from__FEATURE:dashboard"],
    "terms": ["value", "performance"]}}
""".strip()

RELATIONSHIP_EXAMPLE_1 = r"""
{{"relationships": ["ACCOUNT:Nike__had__CONCERN:*"]}}
""".strip()

RELATIONSHIP_EXAMPLE_2 = r"""
{{"relationships": ["ACCOUNT:*__had_issues__CONCERN:performance"]}}
""".strip()

RELATIONSHIP_EXAMPLE_3 = r"""
{{"relationships": ["ACCOUNT:Nike__had__CONCERN:performance",
                      "ACCOUNT:Nike__solved__CONCERN:user_experience"]}}
""".strip()

RELATIONSHIP_EXAMPLE_4 = r"""
{{"relationships": ["ACCOUNT:Nike__had__CONCERN:performance",
                      "ACCOUNT:Nike__had_issues__FEATURE:dashboard",
                      "ACCOUNT:NIKE__gets_value_from__FEATURE:dashboard"]}}
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
should be obvious. You can ONLY extract entities of these types and relationships between objects of these types:
{SEPARATOR_LINE}
{ENTITY_TYPE_SETTING_PROMPT}
{SEPARATOR_LINE}
Please format your answer in this format:
{SEPARATOR_LINE}
{EXTRACTION_FORMATTING_PROMPT}
{SEPARATOR_LINE}

The list above here is the exclusive, only list of entities you can chose from!

Here are some important additional instructions. (For the purpose of illustration, assume that ]
 "ACCOUNT", "CONCERN", and "FEATURE" are all in the list of entity types above. Note that this \
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
can later be matched with a known knowledge graph. You are also asked to extract time filters.

Today is ---today_date---. Here are the entity types that are available for extraction. Some of them may have \
a description, others should be obvious. You can ONLY extract entities of these types:
{SEPARATOR_LINE}
{ENTITY_TYPE_SETTING_PROMPT}
{SEPARATOR_LINE}
Please format your answer in this format:
{SEPARATOR_LINE}
{QUERY_ENTITY_EXTRACTION_FORMATTING_PROMPT}
{SEPARATOR_LINE}

The list above here is the exclusive, only list of entities you can chose from!

Here are some important additional instructions. (For the purpose of illustration, assume that ]
 "ACCOUNT", "CONCERN", and "FEATURE" are all in the list of entity types above. Note that this \
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
""".strip()


QUERY_RELATIONSHIP_EXTRACTION_PROMPT = f"""
You are an expert in the area of knowledge extraction and using knowledge graphs. You are given a question \
and previously you were asked to identify known entities in the question. Now you are asked to extract \
the relationships between the entities you have identified earlier.

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
 'Which issues did Nike report?' and the extracted entities were found to be:

 "ACCOUNT:Nike", "CONCERN:*"

then a valid relationship extraction could be:
Example 1:
{RELATIONSHIP_EXAMPLE_1}

* If on the other hand the question would say:
'Did Nike say anything about performance issues?' and the extracted entities were found to be:

"ACCOUNT:Nike", "CONCERN:performance"

then a much more suitable relationship extraction could be:
Example 2:
{RELATIONSHIP_EXAMPLE_2}

- You can extract multiple relationships between the same two entity types.
As an example, if the question would say:
'Did Nike report some performance issues with our solution? And were they happy that the user experience issue got solved?', \
and the extracted entities were found to be:

"ACCOUNT:Nike", "CONCERN:performance", "CONCERN:user_experience"

then a valid relationship extraction could be:
Example 3:
{RELATIONSHIP_EXAMPLE_3}

- You can extract multiple relationships between the same two actual entities if you think that \
there are multiple relationships between them based on the question.
As an example, if the question would say:
'Nike reported some performance issues with our dashboard solution, but do they think it delivers great value nevertheless?' \
and the extracted entities were found to be:

"ACCOUNT:Nike", "FEATURE:dashboard", "CONCERN:performance"

then a valid relationship extraction could be:
Example 4:
{RELATIONSHIP_EXAMPLE_4}

Note that effectively a three-way relationship (Nike - performance issues - dashboard) extracted as two individual \
relationships.

- Again,
   - you can only extract relationships between the entities extracted earlier
   - you can only extract the relationships that match the listed relationship types
   - only extract important relationships that signify something non-trivial, expressing things like \
needs, wants, likes, dislikes, plans, interests, lack of interests, problems the account is having, etc.

{SEPARATOR_LINE}

Here is the question you are asked to extract desired entities, relationships, and terms from:
{SEPARATOR_LINE}
---content---
{SEPARATOR_LINE}
""".strip()


### Source-specific prompts

FIREFLIES_PREPROCESSING_PROMPT = f"""
This is a call between employees of our company and representatives of one or more accounts (usually one). \
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
    once for the account, i.e. ACCOUNT:{KG_OWN_COMPANY}.
  - if you see a relationship for one of the representatives of other accounts, you should extract the relationship \
only for the account!

--
And here is the content:
{{content}}
"""


STRATEGY_GENERATION_PROMPT = f"""
Now you need to decide what type of strategy to use to answer the question. There are two types of strategies \
available to you:

1. DEEP: You can can leverage the actual text of sources to answer the question, which sits in a vector database.
2. SIMPLE: You can use a simpler database that is aware of the entities, relationships, and terms, and is suitable
if it is enough to either list or count entities or relationships.

Your task is to decide which of the two strategies to use.

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

Please answer simply with 'DEEP' or 'SIMPLE'. Do not include any other text or explanations.
"""


SIMPLE_SQL_PROMPT = f"""
You are an expert in generating a SQL statement that sole uses two tables, one for entities and another for relationships \
between two entities - to find (or count) the correct entities.

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

We already have identified that that the SQL statement should use (only) the following entities and relationships:
{SEPARATOR_LINE}
Query entities (id_name):
---query_entities---

--

Query relationships (id_name):
---query_relationships---

{SEPARATOR_LINE}

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
- The entity table can only be joined ion the relationshiptable which can then be joined again on the entity table, etc.
- Ultimately this should be a select statement that askes about entities, or a select count() of entities.
- Try to be as efficient as possible.

Approach:
Please think through this step by step. Then, when you have it say 'SQL:' followed ONLY by the SQL statement. The SQL statement \
must end with a ';'


Your answer:

"""
