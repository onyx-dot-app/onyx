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
  - if applicable, the plan you had created early on
  - the original context provided in the system prompt, if applicable
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
  - you CAN use information from the base knowledge to provide context and facts to the questions/tasks \
for the tool class you select.
  - the thinking tool, if available, can also use the information and facts from the base knowledge \
to use for reflection.


Your task is to select the next tool to call and the questions/requests to ask of that tool.

"""


EXTRACTION_SYSTEM_PROMPT_TEMPLATE = """
You are an expert in identifying and extracting relevant information and strategies from extracted facts, thoughts, and \
answers provided to a user based on their question, that may be useful in INFORMING FUTURE ANSWER STRATEGIES, and \
updating/extending the previous knowledge accordingly. As such, your updates MUST be correct and broadly informative.

The information to extracted CAN ONLY relate to:
  - information about the user who asks the question
  - information about the company of the user who asks the question
  - search strategies that may be relevant to future questions
  - reasoning strategies that led to interesting results and that may be relevant to future questions

So DO NOT extract information pertaining to other companies, other users, or other topics that are not relevant to the question, \
or any specific that are not expected to be relevant for the context of future questions.

Here is the original knowledge, which also contains the name of the user and their  company:
###
---original_knowledge---
###

You will receive the new information from the user in the next message.

Note:
  - ONLY extract HIGH-LEVEL information THAT is a) HIGH-LEVEL and 'characterizing', b) GENERAL AND LILKELY TO BE TRUE \
FOR MONTHS, and c) WILL LIKELY PROVIDE HELPFUL CONTEXT OR APPROACHES FOR FUTURE QUESTIONS (like for questions including \
'we', 'i', etc.).
  - again, make absolutely sure that new extracted information about the user is actually ABOUT THE USER WHO IS \
ASKING THE QUESTION, and \
extracted information about the company is actually ABOUT THE COMPANY OF THE USER WHO ASKS THE QUESTION!
  - only extract HIGH-LEVEL information that is EXPECTED TO BE RELEVANT & TRUE FOR SOME TIME! This is CRITICAL! Do not extract \
emphemeral facts like what the user was working on last month, but if applicable GENERALIZE (or iognore.). \
Do NOT EXTRACT \
specific information from questions that could have a different answer if asked at a different time.
  - only suggest updates if there is substantially new information that should extend the same type of information \
in the original knowledge.
  - keep the information concise, to the point, and in a way that would be useful to provide context to future questions.
  - it is usually better to 'update' existing information (same key and sub-key) than adding a new information \
type (new sub-key). But if no existing type is a good fit, then add a new information type.
  - the 'type' (see below) must be high-level and cannot contain sub-categories or sub-types.
  - "search_strategy" and "reasoning_strategy" should NEVER contain extracted facts but only strategies.
  - AGAIN, TRY TO CONSOLIDATE 'TYPES' and don't use sub-types or sub-categories. And don't use for example 'models' and \
'model_speed' as separate types. This should just be 'model' where an upate is made should speed information become \
available. Try to reuse types from the original knowledge if possible.


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



"""

CONTEXT_UPDATE_SYSTEM_PROMPT = """
You are an expert in updating/modifying previous knowledge as new information becomes available.
Your task is to generate the updated information that consists of both, the old and the new information.

You will receive the original context and the new information from the user in the next message.

Please responsd with the consolidated information. Keep the information concise, to the point, and in a way \
that would be useful to provide context to future questions.

"""

CS_UPDATE_CONSOLIDATION_PROMPT_TEMPLATE = """
You are an expert in updating existing information with a new piece of information. The consolidated
information will exclusively be used to provide context to future questions, so DO  NOT \
include specific details in your consolidated answer. Also, keep it as concise as possible!

Here is the existing information:
###
---original_information---
###

Here is the new information:
###
---new_information---
###

Please respond with the updated information. Keep the information concise, to the point, and in a way \
that would be useful to provide context to future questions.

"""

CS_COMPRESSION_PROMPT_TEMPLATE = """
You are given a JSON dictionary (the "<starting_dictionary>") of extracted observations. Your task is to \
compress it into a much shorter JSON dictionary of dictionaries that is optimized for being used as \
lightweight context in future questions.

Here is the initial dictionary:

----

---starting_dictionary---

----


Task guidance:
  - Compression requirement
     - Purpose: create a SHORT and CONCISE cheat sheet that can be used to provide CONTEXT \
for future questions
     - Target: around 600 words or less (shorter is fine, as long as it’s still useful). \
Think of this as a high-signal cheat sheet, not a full summary. Err on the side of omitting detail
     - Describes: who the user is and what they work on what the company is and does the core structure of search / \
reasoning strategies
     - Drop: Narrow implementation details. Exhaustive lists of sub-features. Repetitive restatements. Facts that may \
well change within days or weeks. \
Minor edge cases and caveats. Things that are essentially restating the same idea in different words.
     - Be Faithfulness!! No inventions!! You may compress and paraphrase, but you must not invent new facts or implications.
     - Every bullet must be traceable back to content in <starting_dictionary>.
     - Do not infer: personality traits, leadership style, organizational importance, \
unstated responsibilities, or any “likely” facts that \
are not explicitly present.
     - If you NOT 100% SURE whether something is explicitly supported, LEAVE IT OUT!
     - Time handling: Remove explicit dates, years, and phrases like “as of <date>”, “currently”, “recently”.
     - Make sure the information kept GENEALIZES.


For the compression, return valid JSON with the same top-level keys:
{ "user": { ... },
  "company": { ... },
  "search_strategy": { ... },
  "reasoning_strategy": { ... } }

For the top-level areas, please follow these instructions:
   - user:
      - Keep at most 2–3 sub-keys, one of them MUST be 'name'.
      - No inferred importance, no personality traits, no leadership style, etc.
   - company:
      - Keep at most 4–5 sub-keys, one of them MUST be 'name'
      - Only keep information that gives a clear mental model of: what the company is and claims to do, \
how the products work, etc.
  - search_strategy and reasoning_strategy:
      - Each should have at most 3 sub-keys.
      - Each sub-key’s string should be just a few bullets, capturing: how to look for information (search), \
how to summarize / reason over it (reasoning).

For each sub-key:
    - The value must be a single string
    - The string must contain a short bullet list (separated by ' \n - ' as appropriate)
    - Each bullet point must be SHORT and CONCISE
    - Prune aggressively! Only keep information that is:
        - Likely to be useful context for many future questions
        - That is likely to be true for a longer time period
        - If information is tied to a time frame... drop it!
        - Only keep IMPORTANT information
    - Merge aggressively
    - Prefer fewer, denser bullets over many narrow ones.
    - Style of bullet strings For every string value: Use " - " at the start of each bullet. Separate bullets with "\n".
    - No trailing spaces
    - No markdown headings
    - No extra quotation marks beyond valid JSON requirements
    - Keep bullets short and direct
    - Merge overlapping ideas into fewer, stronger bullets
"""

CONTEXT_EXPLORER_PROMPT_TEMPLATE = """
You are an expert in identifying suitable information from a memory that helps to provide \
suitable context for a user question.

The memory may have information about:
 - the user
 - the company where they work
 - successful search strategies
 - successfull reasoning strategies


Your task is to extract components of the memory that are relevant to the user question.

Note:
  - particularly, identify information that could be relevant to make references more specific or \
fill in gaps. Example: if the question refers to 'availabiliity products', and the memory has \
a list of specific products that increase availability, you definitely want to include those \
specific products as 'availability products'.

Here is the user question:
###
---user_question---
###

Here is the current memory:
###
---current_memory---
###

Please respond with a string in this format:
###
  - user
    -<sub-key>: <bullet point list of information about the user RELEVANT as context for the question>
   - company
    -<sub-key>: <bullet point list of information about the company RELEVANT as context for the question>
   - search_strategy
    -<sub-key>: <bullet point list of information about the search strategy RELEVANT as context for the question>
   - reasoning_strategy
    -<sub-key>: <bullet point list of information about the reasoning strategy RELEVANT as context for the question>
###

"""
