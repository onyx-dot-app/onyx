# The following prompts are used for verifying the LLM answer after it is already produced.
# Reflexion flow essentially. This feature can be toggled on/off
from onyx.configs.app_configs import CUSTOM_ANSWER_VALIDITY_CONDITIONS
from onyx.prompts.constants import ANSWER_PAT
from onyx.prompts.constants import QUESTION_PAT

ANSWER_VALIDITY_CONDITIONS = (
    """
1. Query is asking for information that varies by person or is subjective. If there is not a \
globally true answer, the language model should not respond, therefore any answer is invalid.
2. Answer addresses a related but different query. To be helpful, the model may provide \
related information about a query but it won't match what the user is asking, this is invalid.
3. Answer is just some form of "I don\'t know" or "not enough information" without significant \
additional useful information. Explaining why it does not know or cannot answer is invalid.
"""
    if not CUSTOM_ANSWER_VALIDITY_CONDITIONS
    else "\n".join(
        [
            f"{indice+1}. {condition}"
            for indice, condition in enumerate(CUSTOM_ANSWER_VALIDITY_CONDITIONS)
        ]
    )
)

ANSWER_FORMAT = (
    """
1. True or False
2. True or False
3. True or False
"""
    if not CUSTOM_ANSWER_VALIDITY_CONDITIONS
    else "\n".join(
        [
            f"{indice+1}. True or False"
            for indice, _ in enumerate(CUSTOM_ANSWER_VALIDITY_CONDITIONS)
        ]
    )
)

ANSWER_VALIDITY_PROMPT = f"""
You are an assistant to identify invalid query/answer pairs coming from a large language model.
The query/answer pair is invalid if any of the following are True:
{ANSWER_VALIDITY_CONDITIONS}

{QUESTION_PAT} {{user_query}}
{ANSWER_PAT} {{llm_answer}}

------------------------
You MUST answer in EXACTLY the following format:
```
{ANSWER_FORMAT}
Final Answer: Valid or Invalid
```

Hint: Remember, if ANY of the conditions are True, it is Invalid.
""".strip()


# Use the following for easy viewing of prompts
if __name__ == "__main__":
    print(ANSWER_VALIDITY_PROMPT)
