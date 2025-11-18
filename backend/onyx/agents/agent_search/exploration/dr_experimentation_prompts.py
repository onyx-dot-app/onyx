BASE_SYSTEM_MESSAGE_TEMPLATE = """
You are a helpful assistant that can answer questions and help with tasks.

You should answer the user's question based on their needs. Their needs and directions \
are specified as follows:

###
---user_prompt---
###

The current date is ---current_date---.


The answer process may be complex and may involve multiple tool calls. Here is \
a description of the tools that MAY be available to you throughout the conversations \
(note though that not all tools may be available at all times, depending on the context):

###
---available_tool_descriptions_str---
###
---cheat_sheet_string---

Here are some principle reminders about how to answer the user's question:
   - you will derive the answer through conversational steps with the user.
---plan_instruction_insertion---
   - the answer should only be generated using the tools responses and if applicable, \
retrieved documents and information.

"""

PLAN_PROMPT_TEMPLATE = """
Now you should create a plan how to address the user's question.

###
---user_plan_instructions_prompt---
###

"""

ORCHESTRATOR_PROMPT_TEMPLATE = """
Your need to consider the conversation thus far and see what you want to do next in order \
to answer the user's question/task.

Particularly, you should consider the following:

  - the ORIGINAL QUESTION
  - the plan you had created early on
  - the additional context provided in the system prompt, if applicable
  - the questions generated so far and the corresponding answers you have received
  - previous documented thinking processes, if any. In particular, if \
your previous step in the conversation was a thinking step, pay doubly attention to that \
one as it should provide you with clear guaidance for what to do next.
  - the tools you have available, and the instructions you have been given for each tool, \
including how many quesries can be generated in each iteration.


Note:
  - make sure that you don't repeat yourself. If you have already asked a question of the same tool, \
do not ask it again! New questons to the same tool must be substantially different from the previous ones.
  - a previous question can however be asked of a DIFFERENT tool, if there is reason to believe that the \
new tool is suitable for the question.
  - you must make sure that the tool has ALL RELEVANT context to answer the question/adrres the \
request you are posing to it.
  - NEVER answer the question directly! If you do have all of the information available AND you \
do not want to request additional information or make checks, you need to call the CLOSER tool.


Your task is to select the next tool to call and the questions/requests to ask of that tool.

"""

EXTRACTION_SYSTEM_PROMPT_TEMPLATE = """
You are an expert in identifying relevant information and strategies from extracted facts, thoughts, and \
answers provided to a user based on their question, that may be useful in INFORMING FUTURE ANSWER STRATEGIES.
As such, your extractions MUST be correct and broadly informative. You will receive the information fro the user
in the next message.

Conceptual examples are:
  - facts about the user, their team, or their companies that are helpful to  provide context for future questions
  - search strategies
  - reasonaning strategies

Please format the extractions as a json dictionary in this format:
{{
    "user_information": {{<type of user information>: <the extracted information about the user>, ...}},
    "company_information": {{<type of company information>: <the extracted information about the company>, ...}},
    "search_strategies": {{<type of search strategy>: <the extracted information about the search strategy>, ...}},
    "reasoning_strategies": {{<type of reasoning strategy>: <the extracted information about the reasoning strategy>, ...}},
}}

"""

EXTRACTION_SYSTEM_PROMPT = """
You are an expert in identifying relevant information and strategies from extracted facts, thoughts, and \
answers provided to a user based on their question, that may be useful in INFORMING FUTURE ANSWER STRATEGIES, and \
updating/extending the previous knowledge accordingly. As such, your updates MUST be correct and broadly informative.

You will receive the original knowledge and the new information from the user in the next message.

Conceptual examples are:
  - facts about the user, their team, or their companies that are helpful to  provide context for future questions
  - search strategies
  - reasonaning strategies


Please format the extractions as a json dictionary in this format:
{{
    "user": [<list of new information about the user, each formatted as a dictionary in this format:
{{'type': <essentially, a keyword for the type of infotmation, like 'location', 'interest',... >',
  'change_type': <'update', 'delete', or 'add'. 'update' should be selected if this type of information \
exists in the original knowledge but it should be extended/updated, 'delete' if the information in the \
original knowledge is called into question and no final determination can be made, 'add' for a new information type.>,
  'information': <the actual information to be added, updated, or deleted. Do not do a rewrite, just the new \
information.>}}>,.. ],
    "company":  [<list of new information about the user, each formatted as a dictionary in the exact same \
format as above, except for the 'type' key, which should be company-specific instead of user-specific'.>],
    "search_strategy": [<list of new information about the search strategies, each formatted as a dictionary \
in the exact same format as above, except for the 'type' key, which should be search-strategy-specific.>],
    "reasoning_strategy": [<list of new information about the reasoning strategies, each formatted as a \
dictionary in the exact same format as above, except for the 'type' key, which should be reasoning-strategy-specific.>],
}}

Note:
  - make absolutely sure new information about the user is actually ABOUT THE USER WHO IS ASKING THE QUESTION!
  - similar, make sure that new information about the company is actually ABOUT THE COMPANY OF THE USER WHO ASKS THE QUESTION!
  - only suggest updates if there is substantially new information that should extend the same type of information \
in the original knowledge.
  - keep the information concise, to the point, and in a way that would be useful to provide context to future questions.

"""

CONTEXT_UPDATE_SYSTEM_PROMPT = """
You are an expert in updating/modifying previous knowledge as new information becomes available.
Your task is to generate the updated information that consists of both, the old and the new information.

You will receive the original context and the new information from the user in the next message.

Please responsd with the consolidated information. Keep the information concise, to the point, and in a way \
that would be useful to provide context to future questions.

"""
