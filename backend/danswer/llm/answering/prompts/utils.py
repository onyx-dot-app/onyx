from danswer.prompts.direct_qa_prompts import PARAMATERIZED_PROMPT
from danswer.prompts.direct_qa_prompts import PARAMATERIZED_PROMPT_WITHOUT_CONTEXT


def build_dummy_prompt(
    system_prompt: str, task_prompt: str, retrieval_disabled: bool
) -> str:
    if retrieval_disabled:
        return PARAMATERIZED_PROMPT_WITHOUT_CONTEXT.format(
            user_query="<USER_QUERY>",
            system_prompt=system_prompt,
            task_prompt=task_prompt,
        ).strip()

    return PARAMATERIZED_PROMPT.format(
        context_docs_str="<CONTEXT_DOCS>",
        user_query="<USER_QUERY>",
        system_prompt=system_prompt,
        task_prompt=task_prompt,
    ).strip()
