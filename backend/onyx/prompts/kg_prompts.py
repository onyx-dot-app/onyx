# Standards
SEPARATOR_LINE = "-------"

# Framing/Support/Template Prompts
ENTITY_TYPE_SETTING_PROMPT = f"""
{SEPARATOR_LINE}
{{entity_types}}
{SEPARATOR_LINE}
""".strip()


EXTRACTION_FORMATTING_PROMPT = r"""
{{"entities": [<a list of entities of the prescribed entity types that you can reliably identify in the text, \
formatted as '<ENTITY_TYPE_NAME>::<entity_name>' (please use that capitalization). If allowed options \
are provided above, you can only extract those types of entities! Again, there should be an 'Other' \
option. Pick this if none of the others apply.>],
"relationships": [<a list of IMPORTANT relationships between the identified entities, formatted as \
'<SOURCE_ENTITY_TYPE_NAME>::<source_entity_name>__<a word or two that captures the nature \
of the relationship (if appropriate, include a judgment, as in 'likes' or 'dislikes' vs. 'uses', etc.). \
Common relationships may be: 'likes', 'dislikes', 'uses', 'is interested in', 'mentions', 'addresses', \
'participates in', etc., but look at the text to find the most appropriate relationship. \
Use spaces here for word separation. DO NOT INCLUDE RELATIONSHIPS THAT ARE SIMPLY MENTIONED, BUT ONLY \
THOSE THAT ARE CENTRAL TO THE CONTENT! >\
__<TARGET_ENTITY_TYPE_NAME>::<target_entity_name>'>],
"terms": [<a comma-separated list of high-level terms (each one one or two words) that you can reliably \
identify in the text, each formatted simply as '<term>'>]
}}
""".strip()


EXAMPLE_1 = r"""
{{"entities": ["ACCOUNT::Nike", "CONCERN::*"],
    "relationships": ["ACCOUNT::Nike__had__CONCERN::*"], "terms": []}}
""".strip()

EXAMPLE_2 = r"""
{{"entities": ["ACCOUNT::Nike", "CONCERN::performance"],
    "relationships": ["ACCOUNT::*__had_issues__CONCERN::performance"], "terms": ["performance issue"]}}
""".strip()

EXAMPLE_3 = r"""
{{"entities": ["ACCOUNT::Nike", "CONCERN::performance", "CONCERN::user_experience"],
    "relationships": ["ACCOUNT::Nike__had__CONCERN::performance",
                      "ACCOUNT::Nike__solved__CONCERN::user_experience"],
    "terms": ["performance", "user experience"]}}
""".strip()

EXAMPLE_4 = r"""
{{"entities": ["ACCOUNT::Nike", "FEATURE::dashboard", "CONCERN::performance"],
    "relationships": ["ACCOUNT::Nike__had__CONCERN::performance",
                      "ACCOUNT::Nike__had_issues__FEATURE::dashboard",
                      "ACCOUNT::NIKE__gets_value_from__FEATURE::dashboard"],
    "terms": ["value", "performance"]}}
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

The list above here is the exclusive, only list of entities you can choose from!

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
   -  you should only extract entities belonging to the entity types above - but do extract all that you \
can reliably identify in the text
   - use refer to 'all' entities in an entity type listed above by using '*' as the entity name
   - only extract important relationships that signify something non-trivial, expressing things like \
needs, wants, likes, dislikes, plans, interests, lack of interests, problems the account is having, etc.
   - you MUST only use the initial list of entities provided! Ignore the entities in the examples unless \
they are also part of the initial list of entities! This is essential!
   - only extract relationships between the entities extracted first!


{SEPARATOR_LINE}

Here is the text you are asked to extract knowledge from, if needed with additional information about any participants:
{SEPARATOR_LINE}
---content---
{SEPARATOR_LINE}
""".strip()


GENERAL_CHUNK_PREPROCESSING_PROMPT = """
This is a part of a document that you need to extract information (entities, relationships) from.

Note: when you extract relationships, please make sure that:
  - if you see a relationship for one of our employees, you should extract the relationship both for the employee AND \
    VENDOR::{vendor}.
  - if you see a relationship for one of the representatives of other accounts, you should extract the relationship \
only for the account ACCOUNT::<account_name>!

--
And here is the content:
{content}
""".strip()


### Source-specific prompts

CALL_CHUNK_PREPROCESSING_PROMPT = """
This is a call between employees of the VENDOR's company and representatives of one or more ACCOUNTs (usually one). \
When you extract information based on the instructions, please make sure that you properly attribute the information \
to the correct employee and account. \

Here are the participants (name component of email) from us ({vendor}):
{participant_string}

Here are the participants (name component of email) from the other account(s):
{account_participant_string}

In the text it should be easy to associate a name with the email, and then with the account ('us' vs 'them'). If in doubt, \
look at the context and try to identify whether the statement comes from the other account. If you are not sure, ignore.

Note: when you extract relationships, please make sure that:
  - if you see a relationship for one of our employees, you should extract the relationship both for the employee AND \
    VENDOR::{vendor}.
  - if you see a relationship for one of the representatives of other accounts, you should extract the relationship \
only for the account ACCOUNT::<account_name>!

--
And here is the content:
{content}
""".strip()


CALL_DOCUMENT_CLASSIFICATION_PROMPT = """
This is the beginning of a call between employees of the VENDOR's company ({vendor}) and other participants.

Your task is to classify the call into one of the following categories:
{category_options}

Please also consider the participants when you perform your classification task - they can be important indicators \
for the category.

Please format your answer as a string in the format:

REASONING: <your reasoning for the classification> - CATEGORY: <the category you have chosen. Only use {category_list}>

--
And here is the beginning of the call, including title and participants:

{beginning_of_call_content}
""".strip()


# KG Beta Assistant System Prompt
KG_BETA_ASSISTANT_SYSTEM_PROMPT = """"You are a knowledge graph assistant that helps users explore and \
understand relationships between entities."""

KG_BETA_ASSISTANT_TASK_PROMPT = """"Help users explore and understand the knowledge graph by answering \
questions about entities and their relationships."""
