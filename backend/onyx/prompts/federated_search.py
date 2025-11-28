from onyx.configs.app_configs import MAX_SLACK_QUERY_EXPANSIONS

SLACK_QUERY_EXPANSION_PROMPT = f"""
Rewrite the user's query and, if helpful, split it into at most {MAX_SLACK_QUERY_EXPANSIONS} \
keyword-only queries, so that Slack's keyword search yields the best matches.

Keep in mind the Slack's search behavior:
- Pure keyword AND search (no semantics).
- Word order matters.
- More words = fewer matches, so keep each query concise.
- IMPORTANT: Prefer simple 1-2 word queries over longer multi-word queries.

Critical: Extract ONLY keywords that would actually appear in Slack message content.

DO NOT include:
- Meta-words: "topics", "conversations", "discussed", "summary", "messages", "big", "main", "talking"
- Temporal: "today", "yesterday", "week", "month", "recent", "past", "last"
- Channels/Users: "general", "eng-general", "engineering", "@username"

DO include:
- Actual content: "performance", "bug", "deployment", "API", "database", "error", "feature"

Examples:

Query: "what are the big topics in eng-general this week?"
Output:
(empty - contains only meta-words and temporal terms, no actual content keywords)

Query: "performance issues in eng-general"
Output:
performance issues
performance
issues

Query: "what did we discuss about the API migration?"
Output:
API migration
API
migration

Now process this query:

{{query}}

Output:
"""

SLACK_DATE_EXTRACTION_PROMPT = """
Extract the date range from the user's query and return it in a structured format.

Current date context:
- Today: {today}
- Current time: {current_time}

Guidelines:
1. Return a JSON object with "days_back" (integer) indicating how many days back to search
2. If no date/time is mentioned, return {{"days_back": null}}
3. Interpret relative dates accurately:
   - "today" or "today's" = 0 days back
   - "yesterday" = 1 day back
   - "last week" = 7 days back
   - "last month" = 30 days back
   - "last X days" = X days back
   - "past X days" = X days back
   - "this week" = 7 days back
   - "this month" = 30 days back
4. For creative expressions, interpret intent:
   - "recent" = 7 days back
   - "recently" = 7 days back
   - "lately" = 14 days back
5. Always be conservative - if uncertain, use a longer time range

User query: {query}

Return ONLY a valid JSON object in this format: {{"days_back": <integer or null>}}
Nothing else.
"""
