# These prompts are to support tool calling. Currently not used in the main flow or via any configs
# The current generation of LLM is too unreliable for this task.
# Onyx retrieval call as a tool option
DANSWER_TOOL_NAME = "Current Search"
DANSWER_TOOL_DESCRIPTION = (
    "A search tool that can find information on any topic "
    "including up to date and proprietary knowledge."
)


# Tool calling format inspired from LangChain
TOOL_TEMPLATE = """
TOOLS
------
You can use tools to look up information that may be helpful in answering the user's \
original question. The available tools are:

{tool_overviews}

RESPONSE FORMAT INSTRUCTIONS
----------------------------
When responding to me, please output a response in one of two formats:

**Option 1:**
Use this if you want to use a tool. Markdown code snippet formatted in the following schema:

```json
{{
    "action": string, \\ The action to take. {tool_names}
    "action_input": string \\ The input to the action
}}
```

**Option #2:**
Use this if you want to respond directly to the user. Markdown code snippet formatted in the following schema:

```json
{{
    "action": "Final Answer",
    "action_input": string \\ You should put what you want to return to use here
}}
```
"""

# For the case where the user has not configured any tools to call, but still using the tool-flow
# expected format
TOOL_LESS_PROMPT = """
Respond with a markdown code snippet in the following schema:

```json
{{
    "action": "Final Answer",
    "action_input": string \\ You should put what you want to return to use here
}}
```
"""


# Second part of the prompt to include the user query
USER_INPUT = """
USER'S INPUT
--------------------
Here is the user's input \
(remember to respond with a markdown code snippet of a json blob with a single action, and NOTHING else):

{user_input}
"""


# After the tool call, this is the following message to get a final answer
# Tools are not chained currently, the system must provide an answer after calling a tool
TOOL_FOLLOWUP = """
TOOL RESPONSE:
---------------------
{tool_output}

USER'S INPUT
--------------------
Okay, so what is the response to my last comment? If using information obtained from the tools you must \
mention it explicitly without mentioning the tool names - I have forgotten all TOOL RESPONSES!
If the tool response is not useful, ignore it completely.
{optional_reminder}{hint}
IMPORTANT! You MUST respond with a markdown code snippet of a json blob with a single action, and NOTHING else.
"""


# If no tools were used, but retrieval is enabled, then follow up with this message to get the final answer
TOOL_LESS_FOLLOWUP = """
Refer to the following documents when responding to my final query. Ignore any documents that are not relevant.

CONTEXT DOCUMENTS:
---------------------
{context_str}

FINAL QUERY:
--------------------
{user_query}

{hint_text}
"""
