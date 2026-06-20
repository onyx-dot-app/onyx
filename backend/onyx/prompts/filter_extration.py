# The following prompts are used for extracting filters to apply along with the query in the
# document index. For example, a filter for dates or a filter by source type such as GitHub
# or Slack
SOURCES_KEY = "sources"

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


# Used in source_filter.py: decide which connected source(s) an internal search
# should cover, based on the routing instructions, the user's request, and the
# source(s) already searched this turn.
SOURCE_SCOPE_DECISION_PROMPT = f"""
You route an internal search. Based on the conversation — the assistant/persona \
instructions on where to look and what the user asks — decide which connected source(s) \
THIS search should cover.

The default is NO filter (search everything). Only scope when the conversation EXPLICITLY \
names or routes to specific source(s). Scoping is the exception, not the norm.

Routing comes in two shapes — read the instruction to tell them apart:
- SEQUENTIAL / FALLBACK ("check A first, then B"; "try A; if nothing, then B"; "A, \
otherwise B"): search ONE source at a time, in the stated order. Return the FIRST routed \
source NOT already searched this turn. If every routed source has already been searched, \
return the full routed set.
- COMBINED ("search A and B"; "check both A and B"; "look in A, B and C"): search the \
whole named set TOGETHER. Return all named sources on every call, including repeats (a \
repeat re-runs the same set with new query terms).

The conversation may span multiple turns — decide the scope for the CURRENT request:
- A source directive applies to the current request AND to same-topic follow-ups. If the \
current request continues the same task and names no new source, KEEP the earlier \
directive's source(s).
- A new, UNRELATED current request that names no source RESETS to unscoped — do not carry \
a stale directive forward.
- A later request naming a DIFFERENT source OVERRIDES the earlier one — scope to the \
newly named source only.
- If the current request explicitly says to search everywhere / not to filter / across \
all sources, return an empty list, regardless of any earlier directive.

Already searched this turn: {{already_searched}}

Output JSON with one key, "{SOURCES_KEY}" — the connected source(s) to search now:
- Source(s) named/routed (per the shapes above): the source(s) to search now.
- No source named or routed: an empty list (search everything).

Rules:
- A source must be EXPLICITLY mentioned (by name) or routed to. Default to an empty list; \
when in doubt, return an empty list.
- NEVER infer or guess a source from the topic or subject of the request. The subject \
matter of a question (e.g. an HR or billing question) is NOT a source — do not hallucinate \
a filter from it.
- Ignore anything not in the valid sources below.

The valid sources are:
{{valid_sources}}

Answer with ONLY a json, e.g. {{{{"{SOURCES_KEY}": ["confluence"]}}}}, \
{{{{"{SOURCES_KEY}": ["confluence", "github"]}}}}, or {{{{"{SOURCES_KEY}": []}}}}.
""".strip()

# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(TIME_FILTER_PROMPT)
    print("------------------")
    print(SOURCE_SCOPE_DECISION_PROMPT)
