from onyx.llm.factory import get_default_llm
from onyx.llm.utils import llm_response_to_string
from onyx.prompts.answer_validation import ANSWER_VALIDITY_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


@log_function_time()
def get_answer_validity(
    query: str,
    answer: str,
) -> bool:
    def _extract_validity(model_output: str) -> bool:
        if model_output.strip().strip("```").strip().split()[-1].lower() == "invalid":
            return False
        return True  # If something is wrong, let's not toss away the answer

    llm = get_default_llm()

    prompt = ANSWER_VALIDITY_PROMPT.format(user_query=query, llm_answer=answer)
    model_output = llm_response_to_string(llm.invoke(prompt))
    logger.debug(model_output)

    validity = _extract_validity(model_output)

    return validity
