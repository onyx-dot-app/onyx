# The following prompts are used for extracting filters to apply along with the query in the
# document index. For example, a filter for dates or a filter by source type such as GitHub
# or Slack
SOURCES_KEY = "sources"
NEXT_KEY = "next"

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


# Used in source_filter.py: decide, per call, which connected source(s) THIS
# internal search should cover, given the conversation and what's already been tried.
SOURCE_SCOPE_DECISION_PROMPT = f"""
You route an internal search. Based on the conversation — the assistant/persona \
instructions on where to look and what the user asks — and which sources have already \
been searched for this request, decide which connected source(s) THIS search should cover.

The default is NO filter (search everything). Only apply a source filter when the \
conversation EXPLICITLY names or routes to that source. Filtering is the exception, not \
the norm.

Output JSON with two keys, "{SOURCES_KEY}" and "{NEXT_KEY}":
- "{SOURCES_KEY}": the source(s) to search now.
  - Priority / fallback order that EXPLICITLY names sources ("check Zendesk first, then \
Confluence"; "if nothing in the wiki, try GitHub"): return the FIRST named source in that \
order that has NOT already been searched. Just that one source.
  - Several sources EXPLICITLY named with no priority ("search Confluence and GitHub"): \
return all of them.
  - No source explicitly named or routed, OR every routed source has already been \
searched: return an empty list (search everything).
- "{NEXT_KEY}": for a priority/fallback order, the next not-yet-searched source a follow-up \
search would cover after this one (or null if none remain). null otherwise.

Rules:
- A source must be EXPLICITLY mentioned (by name) or routed to in the conversation to be \
filtered on. Default to an empty list; when in doubt, return an empty list.
- NEVER infer or guess a source from the topic or subject of the request. The subject \
matter of a question (e.g. an HR or billing question) is NOT a source — do not hallucinate \
a filter from it.
- Ignore anything not in the valid sources below.

The valid sources are:
{{valid_sources}}

Sources already searched for this request: {{tried_sources}}

Answer with ONLY a json, e.g. {{{{"{SOURCES_KEY}": ["confluence"], "{NEXT_KEY}": "slack"}}}} \
or {{{{"{SOURCES_KEY}": [], "{NEXT_KEY}": null}}}}.
""".strip()

# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(TIME_FILTER_PROMPT)
    print("------------------")
    print(SOURCE_SCOPE_DECISION_PROMPT)
