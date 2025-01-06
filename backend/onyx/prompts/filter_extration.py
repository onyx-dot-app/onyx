# The following prompts are used for extracting filters to apply along with the query in the
# document index. For example, a filter for dates or a filter by source type such as GitHub
# or Slack
from onyx.prompts.constants import SOURCES_KEY


# Smaller followup prompts in time_filter.py
TIME_FILTER_PROMPT = """
You are a tool to identify time filters to apply to a user query for a downstream search \
application. The downstream application is able to use a recency bias or apply a hard cutoff to \
remove all documents before the cutoff. Identify the correct filters to apply for the user query.

The current day and time is {current_day_time_str}.

Always answer with ONLY a json which contains the keys "filter_type", "filter_value", \
"value_multiple" and "date".

The valid values for "filter_type" are "hard cutoff", "favors recent", or "not time sensitive".
The valid values for "filter_value" are "day", "week", "month", "quarter", "half", or "year".
The valid values for "value_multiple" is any number.
The valid values for "date" is a date in format MM/DD/YYYY, ALWAYS follow this format.
""".strip()


# Smaller followup prompts in source_filter.py
# Known issue: LLMs like GPT-3.5 try to generalize. If the valid sources contains "web" but not
# "confluence" and the user asks for confluence related things, the LLM will select "web" since
# confluence is accessed as a website. This cannot be fixed without also reducing the capability
# to match things like repository->github, website->web, etc.
# This is generally not a big issue though as if the company has confluence, hopefully they add
# a connector for it or the user is aware that confluence has not been added.
SOURCE_FILTER_PROMPT = f"""
Given a user query, extract relevant source filters for use in a downstream search tool.
Respond with a json containing the source filters or null if no specific sources are referenced.
ONLY extract sources when the user is explicitly limiting the scope of where information is \
coming from.
The user may provide invalid source filters, ignore those.

The valid sources are:
{{valid_sources}}
{{web_source_warning}}
{{file_source_warning}}


ALWAYS answer with ONLY a json with the key "{SOURCES_KEY}". \
The value for "{SOURCES_KEY}" must be null or a list of valid sources.

Sample Response:
{{sample_response}}
""".strip()

WEB_SOURCE_WARNING = """
Note: The "web" source only applies to when the user specifies "website" in the query. \
It does not apply to tools such as Confluence, GitHub, etc. that have a website.
""".strip()

FILE_SOURCE_WARNING = """
Note: The "file" source only applies to when the user refers to uploaded files in the query.
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(TIME_FILTER_PROMPT)
    print("------------------")
    print(SOURCE_FILTER_PROMPT)
