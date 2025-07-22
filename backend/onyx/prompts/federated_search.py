from onyx.configs.app_configs import MAX_SLACK_QUERY_EXPANSIONS

# TODO: maybe ask it to generate in and from filters, and fuzzy match them later
SLACK_QUERY_EXPANSION_PROMPT = f"""
Rewrite the user's query and, if helpful, split it into at most {MAX_SLACK_QUERY_EXPANSIONS} \
keyword-only queries, so that Slack's keyword search yields the best matches.

Keep in mind the Slack's search behavior:
- Pure keyword AND search (no semantics).
- Word order matters.
- More words = fewer matches, so keep each query concise.

Guidelines:
1. Remove stop-words and obvious noise.
2. Remove or down-weight meta-instructions (e.g., "show me", "summary of", "how do I") that are \
unlikely to appear in the target messages.
3. Stick with words used in the original query. If you need to add implied keywords (e.g., "when did" -> "date"), \
create a separate query for it.
4. If the query has many keywords, produce several focused queries that keep related words together; \
never explode into single-word queries.
5. Preserve phrases that belong together (e.g., "performance issues"); a word may appear in multiple queries.
6. When unsure, produce both a broad and a narrow query.
7. If the user asks for X or Y, create separate queries for X and Y.

Here is the original query:
{{query}}

Return EXACTLY the new query(ies), one per line, at most {MAX_SLACK_QUERY_EXPANSIONS}. Nothing else.
"""
