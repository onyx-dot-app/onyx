# The following prompts are used for extracting filters to apply along with the query in the
# document index. For example, a filter for dates or a filter by source type such as GitHub
# or Slack
SOURCES_KEY = "sources"

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


TIME_SCOPE_DECISION_PROMPT = """
You scope an internal search to a time filter, from the user's conversation. When the \
conversation EXPLICITLY refers to a time the documents should fall within, decide WHICH date \
the time is about ("created" vs "updated") and set the (start, end) bounds; when it refers to \
none, return "updated (None, None)" (search across all time). You scope only by time.

## Guidance

Set a time filter when a time is EXPLICITLY referenced — in the latest message, or in an \
earlier turn it continues. NEVER infer a time from the topic alone. A date that names the \
subject or title of the document sought ("the 2020 GDPR docs", "the FY21 plan") is NOT a \
filter — it says WHAT the document is, not WHEN it was written; let content search match it. \
If no time is referenced, return "updated (None, None)".

When a time IS referenced, first decide WHICH date it is about: use "created" when the time \
is about when the document was created ("created", "sent", "posted", "published", …); \
otherwise use "updated" — for a change or activity ("edited", "changed", "closed", …) and \
for anything not clearly about creation. When unsure, use "updated".

Then the phrasing decides the bounds:

- LOWER BOUND ONLY — an open-ended time toward now ("since March", "recently", "in the last \
2 weeks"). Set start; leave end None — it has no upper bound, so do NOT set end to today.

- UPPER BOUND ONLY — an open-ended time toward the past ("before 2023", "older than \
January", "more than 20 weeks ago"). Set end; leave start None.

- BOTH BOUNDS — a completed, named calendar period ("last quarter", "last January", "Q1 \
2025", "in 2022", "between March and June", a single day like "March 25 2024") or a numeric \
range ("10 to 15 weeks ago"). A named period is NOT a rolling duration — "last quarter" is \
the previous calendar quarter (both bounds), not the last 3 months. Set start to its first \
day / larger offset, end to its last day / smaller offset.

- NO BOUND — a vague preference for fresh results with no actual time ("the latest", "most \
recent"). Return "updated (None, None)".

## Conversation history

{conversation_history}

## Current date

Today is {current_day_time_str}. Use a token "-P<N><U>" — a signed ISO-8601 duration where \
the leading minus means "before today" and U is D=days, W=weeks, M=months, Y=years (e.g. \
-P15W, -P5M, -P30D) — ONLY for a numeric offset — a number the message states followed by a \
time unit ("15 weeks ago", "the last 5 months", "30 to 45 days ago"); then never compute the \
date, the system resolves the token against today. A month or year NAME ("March 2024", "Q1 \
2025", "2022") is NOT a numeric offset — resolve it to an absolute YYYY-MM-DD date yourself, \
never a token.

## Guidance reminder

FIELD: "created" only when the phrasing is clearly about creation; otherwise "updated" (the \
default).
LOWER / UPPER BOUND: an open-ended time sets one bound and leaves the other None — one \
toward now ("the last 2 weeks") leaves end None, not today.
BOTH BOUNDS: a named calendar period ("last quarter", "in 2022") or a numeric range ("10 to \
15 weeks ago") sets both bounds — a named period is never a rolling duration.
A month or year NAME is an absolute date, never a token. NEVER filter on a date that names \
the document's subject/title, and return "updated (None, None)" when no time is referenced.

## Output format

Output ONLY the decision as "<field> (start, end)". <field> is "created" or "updated". Each \
side of the pair is a date "YYYY-MM-DD", a token "-P<N><U>" (a signed ISO-8601 duration \
before today, e.g. -P15W), or None; bounds are inclusive, and None means no bound on that \
side.

Examples:
- "in the last 2 weeks" → updated (-P2W, None)
- "10 to 15 weeks ago" → updated (-P15W, -P10W)
- "more than 20 weeks ago" → updated (None, -P20W)
- "in the last 5 months" → updated (-P5M, None)
- "since March 2025" → updated (2025-03-01, None)
- "created in 2022" → created (2022-01-01, 2022-12-31)
- "posted before 2023" → created (None, 2022-12-31)
- "in January 2025" → updated (2025-01-01, 2025-01-31)
- "the 2020 GDPR docs" → updated (None, None)
- "the latest updates" → updated (None, None)

Do not include any formatting, explanations, or other text aside from the decision.

## Query reminder

The user's latest message is:
{last_user_query}

CRITICAL: output only "<field> (start, end)".
""".strip()
