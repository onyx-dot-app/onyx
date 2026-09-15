from onyx.file_store.utils import slugify_image_name
from onyx.llm.interfaces import LLM
from onyx.llm.models import (
    LanguageModelInput,
    ReasoningEffort,
    SystemMessage,
    UserMessage,
)
from onyx.llm.utils import llm_response_to_string
from onyx.prompts.image_generation import (
    IMAGE_FILE_NAMING_SYSTEM_PROMPT,
    IMAGE_FILE_NAMING_USER_PROMPT,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span, record_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_PROMPT_INPUT_CHARS = 500


def generate_image_file_stem(prompt: str, llm: LLM | None) -> str:
    """Return a short kebab-case stem for a generated image.

    Uses the same style as conversation naming: a few keywords from the
    request. Falls back to a slug of the prompt if no LLM is available or
    the call fails.
    """
    fallback = slugify_image_name(prompt)
    if llm is None or not prompt.strip():
        return fallback

    prompt_messages: LanguageModelInput = [
        SystemMessage(content=IMAGE_FILE_NAMING_SYSTEM_PROMPT),
        UserMessage(
            content=IMAGE_FILE_NAMING_USER_PROMPT.format(
                prompt=prompt.strip()[:_MAX_PROMPT_INPUT_CHARS]
            )
        ),
    ]
    try:
        with llm_generation_span(
            llm=llm,
            flow=LLMFlow.IMAGE_FILE_NAMING,
            input_messages=prompt_messages,
        ) as span_generation:
            response = llm.invoke(prompt_messages, reasoning_effort=ReasoningEffort.OFF)
            record_llm_response(span_generation, response)
            generated = llm_response_to_string(response).strip().strip('"')
        return slugify_image_name(generated) if generated else fallback
    except Exception as error:
        logger.warning("Failed to generate image file name: %s", error)
        return fallback
