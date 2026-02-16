from onyx.configs.app_configs import MAX_SLACK_QUERY_EXPANSIONS

SLACK_QUERY_EXPANSION_PROMPT = f"""
Rewrite the user's query into at most {MAX_SLACK_QUERY_EXPANSIONS} keyword-only queries for Slack's keyword search.

Slack search behavior:
- Pure keyword AND search (no semantics)
- More words = fewer matches, so keep queries concise (1-3 words)

ALWAYS include:
- Person names (e.g., "Sarah Chen", "Mike Johnson") - people search for messages from/about specific people
- Project/product names, technical terms, proper nouns
- Actual content words: "performance", "bug", "deployment", "API", "error"

DO NOT include:
- Meta-words: "topics", "conversations", "discussed", "summary", "messages"
- Temporal: "today", "yesterday", "week", "month", "recent", "last"
- Channel names: "general", "eng-general", "random"

Examples:

Query: "what are the big topics in eng-general this week?"
Output:

Query: "messages with Sarah about the deployment"
Output:
Sarah deployment
Sarah
deployment

Query: "what did Mike say about the budget?"
Output:
Mike budget
Mike
budget

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

Output (keywords only, one per line, NO explanations or commentary):
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
