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

EXAMPLE_1 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:*"],
    "relationships": ["ACCOUNT:Nike__had__CONCERN:*"], "terms": []}}
""".strip()

EXAMPLE_2 = r"""
{{"entities": ["ACCOUNT:Nike", "CONCERN:performance"],
    "relationships": ["ACCOUNT:*__had_issues__CONCERN:performance"], "terms": []}}
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
