from datetime import datetime


# Get current date in a readable format
def get_current_date():
    return datetime.now().strftime("%B %d, %Y")


COMPANY_NAME = "Onyx"

COMPANY_CONTEXT = """
Our company is Onyx, a startup founded by Yuhong Sun and Chris Weaver. Onyx is a startup that provides a platform for
automated research and analysis using AI and LLMss. The current CEO of Onyx is Yuhong Sun. The company is based in San 
Francisco, CA.
"""  # noqa: W291

query_writer_instructions = """Your goal is to generate sophisticated and diverse search queries for an internal search
tool. These queries are intended for an advanced automated research tool capable of analyzing complex results and synthesizing
information. The search tool has access to internal documents and information for {company_name}.

Here is some context about our company:
{company_context}

Instructions:
- Always prefer a single search query, only add another query if the original question requests multiple aspects or elements 
and one query is not enough.
- Each query should focus on one specific aspect of the original question.
- Don't produce more than {number_queries} queries.
- Queries should be diverse, if the topic is broad, generate more than 1 query.
- Don't generate multiple similar queries, 1 is enough.
- Query should ensure that the most current information is gathered. The current date is {current_date}.
- Query should be concise and contain relevant information to the company, the task, and the context.
- Unless the task is general, the query should be specific to the company, the task, and the context.

Format: 
- Format your response as a JSON object with ALL three of these exact keys:
   - "rationale": Brief explanation of why these queries are relevant
   - "query": A list of search queries

Example:

Topic: What revenue grew more last year apple stock or the number of people buying an iphone
```json
{{
    "rationale": "To answer this comparative growth question accurately, we need specific data points on Apple's stock 
        performance and iPhone sales metrics. These queries target the precise financial information needed: company revenue 
        trends, product-specific unit sales figures, and stock price movement over the same fiscal period for direct comparison.",
    "query": [
        "Apple total revenue growth fiscal year 2024",
        "iPhone unit sales growth fiscal year 2024",
        "Apple stock price growth fiscal year 2024",
    ],
}}
```

Context: {user_context}"""  # noqa: W291


reflection_instructions = """You are an expert research assistant analyzing summaries about "{research_topic}" for {company_name}.

Here is some context about our company:
{company_context}

Instructions:
- Identify knowledge gaps or areas that need deeper exploration and generate a follow-up query. (1 or multiple).
- If provided summaries are sufficient to answer the user's question, don't generate a follow-up query.
- If there is a knowledge gap, generate a follow-up query that would help expand your understanding.
- Focus on technical details, implementation specifics, or emerging trends that weren't fully covered.

Requirements:
- Ensure the follow-up query is self-contained and includes necessary context for onyx search, an internal search tool, that
has access to internal documents and information.

Output Format:
- Format your response as a JSON object with these exact keys:
   - "is_sufficient": true or false
   - "knowledge_gap": Describe what information is missing or needs clarification
   - "follow_up_queries": Write a specific question to address this gap

Example:
```json
{{
    "is_sufficient": true, // or false
    "knowledge_gap": "The summary lacks information about performance benchmarks", // "" if is_sufficient is true
    "follow_up_queries":
        ["What are typical performance benchmarks used to evaluate [specific technology]?"] // [] if is_sufficient is true
}}
```

Reflect carefully on the Summaries to identify knowledge gaps and produce a follow-up query.
Then, produce your output following this JSON format:

Summaries:
{summaries}
"""

answer_instructions = """You are an expert research assistant analyzing summaries about "{research_topic}" for {company_name}.

Here is some context about our company:
{company_context}

Generate a high-quality answer to the user's question based on the provided summaries.

Instructions:
- The current date is {current_date}.
- You are the final step of a multi-step research process, don't mention that you are the final step.
- You have access to all the information gathered from the previous steps.
- You have access to the user's question.
- Generate a high-quality answer to the user's question based on the provided summaries and the user's question.
- You MUST include all the citations from the summaries in the answer correctly.
- Only use the information from the summaries to answer the question, do not make up information or speculate.

User Context:
- {user_context}

Summaries:
{summaries}"""

planner_prompt = """You are an expert research assistant for {company_name}.

Here is some context about our company:
{company_context}

For this given objective, come up with a simple step by step plan.
This plan should involve individual tasks, that if executed correctly will yield the correct answer. Do not add any superfluous steps.
The result of the final step should be the final answer. Make sure that each step has all the information needed - do not skip steps.

Example:
Input: What's the population of the city or town where the CEO of Onyx was born?
```json
{{
    "steps": ["Step 1: Search for the CEO of Onyx", "Step 2: Search for the birthplace of the CEO", "Step 3: Find the population of that town or city"]
}}
```

Your objective was this:
{input}
"""  # noqa: E501


replanner_prompt = """You are an expert research assistant for {company_name}.

Here is some context about our company:
{company_context}

For the given objective, come up with a simple step by step plan.
This plan should involve individual tasks, that if executed correctly will yield the correct answer. Do not add any superfluous steps.
The result of the final step should be the final answer. Make sure that each step has all the information needed - do not skip steps.

Your objective was this:
{input}

Your original plan was this:
{plan}

You have currently done the follow steps:
{past_steps}

Update your plan accordingly. If no more steps are needed and you can return to the user, then respond with that. Otherwise, fill out the plan. Only add steps to the plan that still NEED to be done. Do not return previously done steps as part of the plan.

Plan structure:
{{
    "steps": ["Step 1", "Step 2", "Step 3]
}}

Response structure:
{{
    "response": "The final answer to the user's question"
}}

Example Output structure with the plan:
{{
    "action": {{
        "steps": ["Step 1", "Step 2", "Step 3"]
    }}
}}

Example Output structure with the response:
{{
    "action": {{
        "response": "The final answer to the user's question" // This should be the answer from the last step
    }}
}}

Output:
{{
    "action": object // "Response" | "Plan"
}}
"""  # noqa: E501


task_to_query_prompt = """
You are an expert research assistant for {company_name}.

Here is some context about our company:
{company_context}

Given the task and and the context, generate a query to search for the information to answer the task. Return a single query text,
make sure that the query is concise and contain relevant information to the company, the task, and the context.

Initial question: {initial_question}

Task: {task}

Information that we have also gathered so far: {context}

Query:
"""


task_completion_prompt = """You are an expert research assistant for {company_name}.

Here is some context about our company:
{company_context}

For the given task, try to accomplish it in a thorough and return well formed answer.

Your current task is this:
{task}

Your original plan was this:
{plan}

Here is the context of the tasks:
{past_steps}

Answer:
"""  # noqa: E501
