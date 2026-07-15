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
# cycle should cover, given the conversation, the prior cycles this turn, and the
# queries being run this cycle. Filled with: {conversation_history},
# {current_cycle_queries}, {previous_cycles}, {valid_sources}, {last_user_query}.
# Output is a bracketed comma-separated list of sources.
SOURCE_SCOPE_DECISION_PROMPT = """
You scope an internal search to its relevant sources. When the conversation EXPLICITLY \
names source(s) to search, scope to them; when it names none, return [] (search every \
source). You scope only by source — other scoping is handled by other systems. The system \
runs multiple cycles, and the queries and sources of previous cycles are provided as \
context.

## Guidance

Scope to a source when it is EXPLICITLY named — in this cycle's queries, or in an earlier \
turn that this cycle continues. NEVER infer a source from the query's topic (e.g. an HR or \
billing query is not a source). If no source is named, return [].

A source named in an earlier turn still applies to a same-topic follow-up that names no new \
source — keep scoping to it.

When source(s) ARE named, the phrasing decides the mode:

- COMBINED — one or more named sources with NO fallback order ("in Google Drive"; "search \
A and B"; "check both A and B"): scope to all of them every cycle, regardless of previous \
cycles. A single named source is COMBINED — scope to it.

- BACKOFF ("check A first, then B", "try A; if nothing, then B" — an order): scope to ONE \
source per cycle. By DEFAULT ADVANCE — scope to the first named source NOT in any previous \
cycle's searched_sources; a reworded retry of the same search keeps advancing. BUT if this \
cycle's queries are about a clearly DIFFERENT topic than the previous cycle's, re-search the \
source the previous cycle used — it has not been searched for this new topic. Once all named \
sources have been tried, scope to all of them.

Only scope to sources listed in the Valid sources section below. If a named source is not \
listed there, ignore it and scope to the named sources that ARE listed; return [] only when \
none of the named sources are listed.

## Conversation history

{conversation_history}

## Current cycle queries

{current_cycle_queries}

## Previous cycles of this user query

{previous_cycles}

## Valid sources

{valid_sources}

## Guidance reminder

COMBINED ("A and B"): scope to all named sources, every cycle.
BACKOFF ("A first, then B"): by DEFAULT ADVANCE to the first named source not in previous \
cycles' searched_sources (a reworded retry keeps advancing). If this cycle's queries are \
about a clearly DIFFERENT topic than the previous cycle's, re-search the source the previous \
cycle used.
If no source is named anywhere in the conversation, return [].

## Output format

Output a comma separated list of sources within brackets:
[source_1, source_2]

Do not include any formatting, explanations, or other text aside from the list. Provide an \
empty list [] if no source should be scoped this cycle.

## Query reminder

The user's query is:
{last_user_query}

CRITICAL: output only the comma separated list of sources.
""".strip()

# Used in time_filter.py: detect the time an internal search should be restricted
# to and turn it into a "<field> (start, end)" decision — the date field (created
# vs updated) plus an explicit (start, end) pair of ISO dates. The model is given
# today's date and does the relative-date math itself, so ranges and named times
# fall out naturally.
# Filled with: {current_day_time_str}, {conversation_history}, {last_user_query}.
TIME_SCOPE_DECISION_PROMPT = """
You scope an internal search to a time filter, from the user's conversation. When the \
conversation EXPLICITLY refers to a time the documents should fall within, decide WHICH date \
the time is about ("created" vs "updated") and set the (start, end) bounds; when it refers to \
none, return "updated (None, None)" (search across all time). You scope only by time.

## Guidance

Set a time filter when a time is EXPLICITLY referenced — in the latest message, or in an \
earlier turn it continues. NEVER infer a time from the topic alone. Only filter on a time \
about the document itself — when it was created or updated. If no such time is referenced, \
return "updated (None, None)".

A date that instead names the document's SUBJECT is NOT a filter — its title ("the 2020 GDPR \
docs"), or when a real-world event it describes occurred ("the breach that occurred on \
August 9"; a write-up is often authored before or after the event, and any clock time like \
"9am–5pm" describes the event, not the document) — let content search match it. A date about \
the documents themselves still IS a filter ("notes from April 4" filters to that day).

When a time IS referenced, first decide WHICH date it is about: use "created" when the time \
is about when the document was created ("created", "sent", "posted", "published", …); \
otherwise use "updated" — for a change or activity ("edited", "changed", "closed", …) and \
for anything not clearly about creation. When unsure, use "updated".

Then the phrasing decides the bounds:

- LOWER BOUND ONLY — an open-ended time toward now ("since March", "recently", "in the last \
2 weeks"). Set start; leave end None — do NOT set end to today.

- UPPER BOUND ONLY — an open-ended time toward the past ("before 2023", "more than 20 weeks \
ago"). Set end; leave start None.

- BOTH BOUNDS — a completed, named calendar period ("last quarter", "in 2022", "between \
March and June", a single day) or a numeric range ("10 to 15 weeks ago"). A named period is \
NOT a rolling duration — "last quarter" is the previous calendar quarter, not the last 3 \
months.

- NO BOUND — a vague freshness preference with no actual time ("the latest", "most \
recent"). Return "updated (None, None)".

## Conversation history

{conversation_history}

## Current date

Today is {current_day_time_str}. Use a token "-P<N><U>" (U: D=days, W=weeks, M=months, \
Y=years; e.g. -P15W) ONLY for a numeric offset — a number the message states followed by a \
time unit ("15 weeks ago", "the last 5 months"); never compute the date, the system \
resolves the token against today. A vague quantity of units ("a few weeks", "several \
months") is still a numeric offset — estimate the number (e.g. "a few weeks" → -P3W). A \
month or year NAME ("March 2024", "2022") is NOT a numeric offset — resolve it to an \
absolute YYYY-MM-DD date yourself, never a token.

## Guidance reminder

FIELD: "created" only when the phrasing is clearly about creation; otherwise "updated" (the \
default).
BOUNDS: an open-ended time sets one bound and leaves the other None ("the last 2 weeks" \
leaves end None, not today); a named calendar period or numeric range sets both.
NEVER filter on a date that names the document's subject; return "updated (None, None)" \
when no time about the document is referenced.

## Output format

Output ONLY the decision as "<field> (start, end)". <field> is "created" or "updated". Each \
side of the pair is a date "YYYY-MM-DD", a token "-P<N><U>", or None; bounds are inclusive, \
and None means no bound on that side.

Examples:
- "in the last 2 weeks" → updated (-P2W, None)
- "10 to 15 weeks ago" → updated (-P15W, -P10W)
- "more than 20 weeks ago" → updated (None, -P20W)
- "in January 2025" → updated (2025-01-01, 2025-01-31)
- "created in 2022" → created (2022-01-01, 2022-12-31)
- "posted before 2023" → created (None, 2022-12-31)
- "the outage that occurred on March 3" → updated (None, None)
- "the latest updates" → updated (None, None)

Do not include any formatting, explanations, or other text aside from the decision.

## Query reminder

The user's latest message is:
{last_user_query}

CRITICAL: output only "<field> (start, end)".
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(TIME_FILTER_PROMPT)
    print("------------------")
    print(TIME_SCOPE_DECISION_PROMPT)
    print("------------------")
    print(SOURCE_SCOPE_DECISION_PROMPT)
