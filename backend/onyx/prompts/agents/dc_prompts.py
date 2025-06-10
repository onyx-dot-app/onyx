# Standards
SEPARATOR_LINE = "-------"
SEPARATOR_LINE_LONG = "---------------"
NO_EXTRACTION = "No extraction of knowledge graph objects was feasable."
YES = "yes"
NO = "no"
DC_OBJECT_SEPARATOR = ";"


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
Here are the task instructions you should use to help you find the desired objects:
{SEPARATOR_LINE}
{{task}}
{SEPARATOR_LINE}
Here is the question that may provide critical additional context for the task:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}
Please answer the question in the following format:
REASONING: <your reasoning for the classification> - OBJECTS: <the objects - just their names - that you found, \
separated by ';'>
""".strip()


DC_OBJECT_WITH_BASE_DATA_EXTRACTION_PROMPT = f"""
You are an expert in finding relevant objects/object specifications of the same type in a list of documents. \
In this case you are interested \
in generating: {{objects_of_interest}}.
You should look at the provided data - in no particular order! - and extract each object you find in the documents.
{SEPARATOR_LINE}
Here are the data provided by the user:
--
{{base_data}}
{SEPARATOR_LINE}
Here are the task instructions you should use to help you find the desired objects:
{SEPARATOR_LINE}
{{task}}
{SEPARATOR_LINE}
Here is the request that may provide critical additional context for the task:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}
Please address the request in the following format:
REASONING: <your reasoning for the classification> - OBJECTS: <the objects - just their names - that you found, \
separated by ';'>
""".strip()


DC_OBJECT_SOURCE_RESEARCH_PROMPT = f"""
Today is {{today}}. You are an expert in extracting relevant structured information from a list of documents that \
should relate to one object. (Try to make sure that you know it relates to that one object!).
You should look at the documents - in no particular order! - and extract the information asked for this task:
{SEPARATOR_LINE}
{{task}}
{SEPARATOR_LINE}

Here is the user question that may provide critical additional context for the task:
{SEPARATOR_LINE}
{{question}}
{SEPARATOR_LINE}

Here are the documents you are supposed to search through:
--
{{document_text}}
{SEPARATOR_LINE}
Note: please cite your sources inline as you generate the results! Use the format [1], etc. Infer the \
number from the provided context documents. This is very important!
Please address the task in the following format:
REASONING:
 -- <your reasoning for the classification>
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
Here is the user question that may provide critical additional context for the task:
{SEPARATOR_LINE}
{{question}}
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


DC_FORMATTING_NO_BASE_DATA_PROMPT = f"""
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
Please start the generation directly with the formatted text. (Note that the output should not be code, but text.)
"""

DC_FORMATTING_WITH_BASE_DATA_PROMPT = f"""
You are an expert in text formatting. Your task is to take a given text and the initial \
base data provided by the user, and convert it 100 percent accurately \
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
Please start the generation directly with the formatted text. (Note that the output should not be code, but text.)
"""
