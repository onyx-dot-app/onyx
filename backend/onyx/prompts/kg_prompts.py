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


EXTRACTION_FORMATTING_PROMPT = """
{{"entities": [<a list of entities of the prescripted entity types that you can reliably identify in the text, \
formatted as '<ENTITY_TYPE_NAME>:<entity_name>' (please use that capitalization)>],
"relationships": [<a list of relationship between the identified entities, formatted as \
'<SOURCE_ENTITY_TYPE_NAME>:<source_entity_name>__<a word or two that captures the nature \
of therelationship>__<TARGET_ENTITY_TYPE_NAME>:<target_entity_name>'>],
"terms": [<a comma-separated list of high-level terms (each one one or two words) that you can reliably \
identify in the text, each formatted simply as '<term>'>]
}}
""".strip()

MASTER_EXTRACTION_PROMPT = """
You are an expert in the area of knowledge extraction in order to construct a knowledge graph. You are given a text \
and asked to extract entities, relationships, and terms from it that you can reliably identify.

Here are the entity types that are available for extraction (you can only extract entities of these types and \
relationships between objects of these types!):
{SEPARATOR_LINE}
{ENTITY_TYPE_SETTING_PROMPT}
{SEPARATOR_LINE}
Please format your answer in this format:
{SEPARATOR_LINE}
{EXTRACTION_FORMATTING_PROMPT}
{SEPARATOR_LINE}

Here are some important additional instructions. (For the purpose of illustration, assume that
 "ACCOUNT", "PROBLEM", and "FEATURE" are all in the list of entity types above.)

- You can either extract specific entities if a specific entity is referred to, or you can refer to the entity type.
* if the entity type is referred to in general, you would use '*' as the entity name in the extraction.
As an example, if the text would say:
 'Nike reported that they had issues'
then a valid extraction could be:
  {{"entities": ['ACCOUNT:Nike', 'PROBLEM:*'],
    "relationships": ['ACCOUNT:Nike__had_issues__PROBLEM:*'], "terms": []}}

* If on the other hand the text would say:
'Nike reported that they had performance issues'
then a much more suitable extraction could be:
  {{"entities": ['ACCOUNT:Nike', 'PROBLEM:performance'],
    "relationships": ['ACCOUNT:*__had_issues__PROBLEM:performance'], "terms": ['performance']}}

- You can extract multiple relationships between the same two entity types.
As an example, if the text would say:
'Nike reported some performance issues with our solution, but they are very happy with the user experience.'
then a valid extraction could be:
  {{"entities": ['ACCOUNT:Nike', 'PROBLEM:performance', 'PROBLEM:user_experience'],
    "relationships": ['ACCOUNT:Nike__had_issues__PROBLEM:performance',
                      'ACCOUNT:Nike__is_happy_with__PROBLEM:user_experience'],
    "terms": ['performance', 'user experience']}}

- You can extract multiple relationships between the same two entities if you think that \
there are multiple relationships between them based on the text.
As an example, if the text would say:
'Nike reported some performance issues with our dashboard solution, but they think it delivers great value.'
then a valid extraction could be:
  {{"entities": ['ACCOUNT:Nike', 'FEATURE:dashboard, 'PROBLEM:performance'],
    "relationships": ['ACCOUNT:Nike__had_issues__PROBLEM:performance',
                      'ACCOUNT:Nike__had_issues__FEATURE:dashboard',
                      'ACCOUNT:NIKE__gets_value_from__FEATURE:dashboard'],
    "terms": ['value', 'performance']}}
Note that effectively a three-way relationship (Nike - performance issues - dashboard) extracted as two individual \
relationships.

{SEPARATOR_LINE}

Here is the text you are asked to extract knowledge from:
{SEPARATOR_LINE}
{text}
{SEPARATOR_LINE}
"""
