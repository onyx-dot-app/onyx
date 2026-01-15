# ruff: noqa: E501, W605 start
SEARCH_CLASS = "search"
CHAT_CLASS = "chat"
SEARCH_CHAT_PROMPT = f"""
Determine if the following query is better suited for a search UI or a chat UI. Respond with "{SEARCH_CLASS}" or "{CHAT_CLASS}" literally and nothing else. \
Do not provide any additional text or reasoning to your response. CRITICAL, IT MUST ONLY BE 1 SINGLE WORD - EITHER "{SEARCH_CLASS}" or "{CHAT_CLASS}".

# Classification Guidelines:
## {SEARCH_CLASS}
- If the query consistents entirely of keywords or query doesn't require any answer from the AI
- If the query is a short statement that seems like a search query rather than a question
- If the query feels nonsensical or is a short phrase that possibly describes a document or information that could be found in a internal document

### Examples of {SEARCH_CLASS} queries:
- Find me the document that goes over the onboarding process for a new hire
- Pull requests since last week
- Sales Runbook AMEA Region
- Procurement process
- Retrieve the PRD for project X

## {CHAT_CLASS}
- If the query is asking a question that requires an answer rather than a document
- If the query is asking for a solution, suggestion, or general help
- If the query is seeking information that is on the web and likely not in a company internal document
- If the query should be answered without any context from additional documents or searches

### Examples of {CHAT_CLASS} queries:
- What led us to win the deal with company X? (seeking answer)
- Google Drive not sync-ing files to my computer (seeking solution)
- Review my email: <whatever the email is> (general help)
- Write me a script to... (general help)
- Cheap flights Europe to Tokyo (information likely found on the web, not internal)

# User Query:
{{user_query}}

REMEMBER TO ONLY RESPOND WITH "{SEARCH_CLASS}" OR "{CHAT_CLASS}" AND NOTHING ELSE.
""".strip()
# ruff: noqa: E501, W605 end
