# The following prompts are used for verifying if the user's query can be answered by the current
# system. Many new users do not understand the design/capabilities of the system and will ask
# questions that are unanswerable such as aggregations or user specific questions that the system
# cannot handle, this is used to identify those cases
from onyx.prompts.constants import ANSWERABLE_PAT
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.prompts.constants import QUESTION_PAT
from onyx.prompts.constants import THOUGHT_PAT


ANSWERABLE_PROMPT = f"""
You are a helper tool to determine if a query is answerable using retrieval augmented generation.
The main system will try to answer the user query based on ONLY the top 5 most relevant \
documents found from search.
Sources contain both up to date and proprietary information for the specific team.
For named or unknown entities, assume the search will find relevant and consistent knowledge \
about the entity.
The system is not tuned for writing code.
The system is not tuned for interfacing with structured data via query languages like SQL.
If the question might not require code or query language, then assume it can be answered without \
code or query language.
Determine if that system should attempt to answer.
"ANSWERABLE" must be exactly "True" or "False"

{GENERAL_SEP_PAT}

{QUESTION_PAT.upper()} What is this Slack channel about?
```
{THOUGHT_PAT.upper()} First the system must determine which Slack channel is being referred to. \
By fetching 5 documents related to Slack channel contents, it is not possible to determine which \
Slack channel the user is referring to.
{ANSWERABLE_PAT.upper()} False
```

{QUESTION_PAT.upper()} Onyx is unreachable.
```
{THOUGHT_PAT.upper()} The system searches documents related to Onyx being unreachable. \
Assuming the documents from search contains situations where Onyx is not reachable and \
contains a fix, the query may be answerable.
{ANSWERABLE_PAT.upper()} True
```

{QUESTION_PAT.upper()} How many customers do we have
```
{THOUGHT_PAT.upper()} Assuming the retrieved documents contain up to date customer acquisition \
information including a list of customers, the query can be answered. It is important to note \
that if the information only exists in a SQL database, the system is unable to execute SQL and \
won't find an answer.
{ANSWERABLE_PAT.upper()} True
```

{QUESTION_PAT.upper()} {{user_query}}
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(ANSWERABLE_PROMPT)
