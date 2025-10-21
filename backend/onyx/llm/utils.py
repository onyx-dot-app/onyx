import copy
import io
import json
from collections.abc import Callable
from collections.abc import Iterator
from functools import lru_cache
from typing import Any
from typing import cast
from typing import TYPE_CHECKING

from langchain.prompts.base import StringPromptValue
from langchain.prompts.chat import ChatPromptValue
from langchain.schema import PromptValue
from langchain.schema.language_model import LanguageModelInput
from langchain.schema.messages import AIMessage
from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage
from langchain.schema.messages import SystemMessage
from sqlalchemy import select

from onyx.configs.app_configs import LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS
from onyx.configs.app_configs import MAX_TOKENS_FOR_FULL_INCLUSION
from onyx.configs.app_configs import USE_CHUNK_SUMMARY
from onyx.configs.app_configs import USE_DOCUMENT_SUMMARY
from onyx.configs.constants import MessageType
from onyx.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from onyx.configs.model_configs import GEN_AI_MAX_TOKENS
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.configs.model_configs import GEN_AI_NUM_RESERVED_OUTPUT_TOKENS
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.prompts.chat_prompts import CONTEXTUAL_RAG_TOKEN_ESTIMATE
from onyx.prompts.chat_prompts import DOCUMENT_SUMMARY_TOKEN_ESTIMATE
from onyx.prompts.constants import CODE_BLOCK_PAT
from onyx.utils.b64 import get_image_type
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger
from shared_configs.configs import LOG_LEVEL


if TYPE_CHECKING:
    from onyx.server.manage.llm.models import LLMProviderView


logger = setup_logger()

MAX_CONTEXT_TOKENS = 100
ONE_MILLION = 1_000_000
CHUNKS_PER_DOC_ESTIMATE = 5


def litellm_exception_to_error_msg(
    e: Exception,
    llm: LLM,
    fallback_to_error_msg: bool = False,
    custom_error_msg_mappings: (
        dict[str, str] | None
    ) = LITELLM_CUSTOM_ERROR_MESSAGE_MAPPINGS,
) -> str:
    from litellm.exceptions import BadRequestError
    from litellm.exceptions import AuthenticationError
    from litellm.exceptions import PermissionDeniedError
    from litellm.exceptions import NotFoundError
    from litellm.exceptions import UnprocessableEntityError
    from litellm.exceptions import RateLimitError
    from litellm.exceptions import ContextWindowExceededError
    from litellm.exceptions import APIConnectionError
    from litellm.exceptions import APIError
    from litellm.exceptions import Timeout
    from litellm.exceptions import ContentPolicyViolationError
    from litellm.exceptions import BudgetExceededError

    error_msg = str(e)

    if custom_error_msg_mappings:
        for error_msg_pattern, custom_error_msg in custom_error_msg_mappings.items():
            if error_msg_pattern in error_msg:
                return custom_error_msg

    if isinstance(e, BadRequestError):
        error_msg = "Bad request: The server couldn't process your request. Please check your input."
    elif isinstance(e, AuthenticationError):
        error_msg = "Authentication failed: Please check your API key and credentials."
    elif isinstance(e, PermissionDeniedError):
        error_msg = (
            "Permission denied: You don't have the necessary permissions for this operation."
            "Ensure you have access to this model."
        )
    elif isinstance(e, NotFoundError):
        error_msg = "Resource not found: The requested resource doesn't exist."
    elif isinstance(e, UnprocessableEntityError):
        error_msg = "Unprocessable entity: The server couldn't process your request due to semantic errors."
    elif isinstance(e, RateLimitError):
        error_msg = (
            "Rate limit exceeded: Please slow down your requests and try again later."
        )
    elif isinstance(e, ContextWindowExceededError):
        error_msg = (
            "Context window exceeded: Your input is too long for the model to process."
        )
        if llm is not None:
            try:
                max_context = get_max_input_tokens(
                    model_name=llm.config.model_name,
                    model_provider=llm.config.model_provider,
                )
                error_msg += f"Your invoked model ({llm.config.model_name}) has a maximum context size of {max_context}"
            except Exception:
                logger.warning(
                    "Unable to get maximum input token for LiteLLM excpetion handling"
                )
    elif isinstance(e, ContentPolicyViolationError):
        error_msg = "Content policy violation: Your request violates the content policy. Please revise your input."
    elif isinstance(e, APIConnectionError):
        error_msg = "API connection error: Failed to connect to the API. Please check your internet connection."
    elif isinstance(e, BudgetExceededError):
        error_msg = (
            "Budget exceeded: You've exceeded your allocated budget for API usage."
        )
    elif isinstance(e, Timeout):
        error_msg = "Request timed out: The operation took too long to complete. Please try again."
    elif isinstance(e, APIError):
        error_msg = f"API error: An error occurred while communicating with the API. Details: {str(e)}"
    elif not fallback_to_error_msg:
        error_msg = "An unexpected error occurred while processing your request. Please try again later."
    return error_msg


def _build_content(
    message: str,
    files: list[InMemoryChatFile] | None = None,
) -> str:
    """Applies all non-image files."""
    from onyx.file_processing.extract_file_text import read_pdf_file

    if not files:
        return message

    text_files = [file for file in files if file.file_type.is_text_file()]

    if not text_files:
        return message

    final_message_with_files = "FILES:\n\n"
    for file in text_files:
        try:
            file_content = file.content.decode("utf-8")
        except UnicodeDecodeError:
            # Try to decode as binary
            try:
                file_content, _, _ = read_pdf_file(io.BytesIO(file.content))
            except Exception:
                file_content = f"[Binary file content - {file.file_type} format]"
                logger.exception(
                    f"Could not decode binary file content for file type: {file.file_type}"
                )
                # logger.warning(f"Could not decode binary file content for file type: {file.file_type}")
        file_name_section = f"DOCUMENT: {file.filename}\n" if file.filename else ""
        final_message_with_files += (
            f"{file_name_section}{CODE_BLOCK_PAT.format(file_content.strip())}\n\n\n"
        )

    return final_message_with_files + message


def build_content_with_imgs(
    message: str,
    files: list[InMemoryChatFile] | None = None,
    img_urls: list[str] | None = None,
    b64_imgs: list[str] | None = None,
    message_type: MessageType = MessageType.USER,
    exclude_images: bool = False,
) -> str | list[str | dict[str, Any]]:  # matching Langchain's BaseMessage content type
    files = files or []

    # Only include image files for user messages
    img_files = (
        [file for file in files if file.file_type == ChatFileType.IMAGE]
        if message_type == MessageType.USER
        else []
    )

    img_urls = img_urls or []
    b64_imgs = b64_imgs or []
    message_main_content = _build_content(message, files)

    if exclude_images or (not img_files and not img_urls):
        return message_main_content

    return cast(
        list[str | dict[str, Any]],
        [
            {
                "type": "text",
                "text": message_main_content,
            },
        ]
        + [
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{get_image_type_from_bytes(file.content)};"
                        f"base64,{file.to_base64()}"
                    ),
                },
            }
            for file in img_files
        ]
        + [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{get_image_type(b64_img)};base64,{b64_img}",
                },
            }
            for b64_img in b64_imgs
        ]
        + [
            {
                "type": "image_url",
                "image_url": {
                    "url": url,
                },
            }
            for url in img_urls
        ],
    )


def message_to_prompt_and_imgs(message: BaseMessage) -> tuple[str, list[str]]:
    if isinstance(message.content, str):
        return message.content, []

    imgs = []
    texts = []
    for part in message.content:
        if isinstance(part, dict):
            if part.get("type") == "image_url":
                img_url = part.get("image_url", {}).get("url")
                if img_url:
                    imgs.append(img_url)
            elif part.get("type") == "text":
                text = part.get("text")
                if text:
                    texts.append(text)
        else:
            texts.append(part)

    return "".join(texts), imgs


def dict_based_prompt_to_langchain_prompt(
    messages: list[dict[str, str]],
) -> list[BaseMessage]:
    prompt: list[BaseMessage] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not role:
            raise ValueError(f"Message missing `role`: {message}")
        if not content:
            raise ValueError(f"Message missing `content`: {message}")
        elif role == "user":
            prompt.append(HumanMessage(content=content))
        elif role == "system":
            prompt.append(SystemMessage(content=content))
        elif role == "assistant":
            prompt.append(AIMessage(content=content))
        else:
            raise ValueError(f"Unknown role: {role}")
    return prompt


def str_prompt_to_langchain_prompt(message: str) -> list[BaseMessage]:
    return [HumanMessage(content=message)]


def convert_lm_input_to_basic_string(lm_input: LanguageModelInput) -> str:
    """Heavily inspired by:
    https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain/chat_models/base.py#L86
    """
    prompt_value = None
    if isinstance(lm_input, PromptValue):
        prompt_value = lm_input
    elif isinstance(lm_input, str):
        prompt_value = StringPromptValue(text=lm_input)
    elif isinstance(lm_input, list):
        prompt_value = ChatPromptValue(messages=lm_input)

    if prompt_value is None:
        raise ValueError(
            f"Invalid input type {type(lm_input)}. "
            "Must be a PromptValue, str, or list of BaseMessages."
        )

    return prompt_value.to_string()


def message_to_string(message: BaseMessage) -> str:
    if not isinstance(message.content, str):
        raise RuntimeError("LLM message not in expected format.")

    return message.content


def message_generator_to_string_generator(
    messages: Iterator[BaseMessage],
) -> Iterator[str]:
    for message in messages:
        yield message_to_string(message)


def should_be_verbose() -> bool:
    return LOG_LEVEL == "debug"


# estimate of the number of tokens in an image url
# is correct when downsampling is used. Is very wrong when OpenAI does not downsample
# TODO: improve this
_IMG_TOKENS = 85


def check_message_tokens(
    message: BaseMessage, encode_fn: Callable[[str], list] | None = None
) -> int:
    if isinstance(message.content, str):
        return check_number_of_tokens(message.content, encode_fn)

    total_tokens = 0
    for part in message.content:
        if isinstance(part, str):
            total_tokens += check_number_of_tokens(part, encode_fn)
            continue

        if part["type"] == "text":
            total_tokens += check_number_of_tokens(part["text"], encode_fn)
        elif part["type"] == "image_url":
            total_tokens += _IMG_TOKENS

    if isinstance(message, AIMessage) and message.tool_calls:
        for tool_call in message.tool_calls:
            total_tokens += check_number_of_tokens(
                json.dumps(tool_call["args"]), encode_fn
            )
            total_tokens += check_number_of_tokens(tool_call["name"], encode_fn)

    return total_tokens


def check_number_of_tokens(
    text: str, encode_fn: Callable[[str], list] | None = None
) -> int:
    """Gets the number of tokens in the provided text, using the provided encoding
    function. If none is provided, default to the tiktoken encoder used by GPT-3.5
    and GPT-4.
    """
    import tiktoken

    if encode_fn is None:
        encode_fn = tiktoken.get_encoding("cl100k_base").encode

    return len(encode_fn(text))


def test_llm(llm: LLM) -> str | None:
    # try for up to 2 timeouts (e.g. 10 seconds in total)
    error_msg = None
    for _ in range(2):
        try:
            llm.invoke("Do not respond")
            return None
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Failed to call LLM with the following error: {error_msg}")

    return error_msg


@lru_cache(maxsize=1)  # the copy.deepcopy is expensive, so we cache the result
def get_model_map() -> dict:
    import litellm

    DIVIDER = "/"

    original_map = cast(dict[str, dict], litellm.model_cost)
    starting_map = copy.deepcopy(original_map)
    for key in original_map:
        if DIVIDER in key:
            truncated_key = key.split(DIVIDER)[-1]
            # make sure not to overwrite an original key
            if truncated_key in original_map:
                continue

            # if there are multiple possible matches, choose the most "detailed"
            # one as a heuristic. "detailed" = the description of the model
            # has the most filled out fields.
            existing_truncated_value = starting_map.get(truncated_key)
            potential_truncated_value = original_map[key]
            if not existing_truncated_value or len(potential_truncated_value) > len(
                existing_truncated_value
            ):
                starting_map[truncated_key] = potential_truncated_value

    # NOTE: we could add additional models here in the future,
    # but for now there is no point. Ollama allows the user to
    # to specify their desired max context window, and it's
    # unlikely to be standard across users even for the same model
    # (it heavily depends on their hardware). For now, we'll just
    # rely on GEN_AI_MODEL_FALLBACK_MAX_TOKENS to cover this.
    # for model_name in [
    #     "llama3.2",
    #     "llama3.2:1b",
    #     "llama3.2:3b",
    #     "llama3.2:11b",
    #     "llama3.2:90b",
    # ]:
    #     starting_map[f"ollama/{model_name}"] = {
    #         "max_tokens": 128000,
    #         "max_input_tokens": 128000,
    #         "max_output_tokens": 128000,
    #     }

    return starting_map


def _strip_extra_provider_from_model_name(model_name: str) -> str:
    return model_name.split("/")[1] if "/" in model_name else model_name


def _strip_colon_from_model_name(model_name: str) -> str:
    return ":".join(model_name.split(":")[:-1]) if ":" in model_name else model_name


def find_model_obj(model_map: dict, provider: str, model_name: str) -> dict | None:
    stripped_model_name = _strip_extra_provider_from_model_name(model_name)

    model_names = [
        model_name,
        _strip_extra_provider_from_model_name(model_name),
        # Remove leading extra provider. Usually for cases where user has a
        # customer model proxy which appends another prefix
        # remove :XXXX from the end, if present. Needed for ollama.
        _strip_colon_from_model_name(model_name),
        _strip_colon_from_model_name(stripped_model_name),
    ]

    # Filter out None values and deduplicate model names
    filtered_model_names = [name for name in model_names if name]

    # First try all model names with provider prefix
    for model_name in filtered_model_names:
        model_obj = model_map.get(f"{provider}/{model_name}")
        if model_obj:
            return model_obj

    # Then try all model names without provider prefix
    for model_name in filtered_model_names:
        model_obj = model_map.get(model_name)
        if model_obj:
            return model_obj

    return None


def get_llm_contextual_cost(
    llm: LLM,
) -> float:
    """
    Approximate the cost of using the given LLM for indexing with Contextual RAG.

    We use a precomputed estimate for the number of tokens in the contextualizing prompts,
    and we assume that every chunk is maximized in terms of content and context.
    We also assume that every document is maximized in terms of content, as currently if
    a document is longer than a certain length, its summary is used instead of the full content.

    We expect that the first assumption will overestimate more than the second one
    underestimates, so this should be a fairly conservative price estimate. Also,
    this does not account for the cost of documents that fit within a single chunk
    which do not get contextualized.
    """

    import litellm

    # calculate input costs
    num_tokens = ONE_MILLION
    num_input_chunks = num_tokens // DOC_EMBEDDING_CONTEXT_SIZE

    # We assume that the documents are MAX_TOKENS_FOR_FULL_INCLUSION tokens long
    # on average.
    num_docs = num_tokens // MAX_TOKENS_FOR_FULL_INCLUSION

    num_input_tokens = 0
    num_output_tokens = 0

    if not USE_CHUNK_SUMMARY and not USE_DOCUMENT_SUMMARY:
        return 0

    if USE_CHUNK_SUMMARY:
        # Each per-chunk prompt includes:
        # - The prompt tokens
        # - the document tokens
        # - the chunk tokens

        # for each chunk, we prompt the LLM with the contextual RAG prompt
        # and the full document content (or the doc summary, so this is an overestimate)
        num_input_tokens += num_input_chunks * (
            CONTEXTUAL_RAG_TOKEN_ESTIMATE + MAX_TOKENS_FOR_FULL_INCLUSION
        )

        # in aggregate, each chunk content is used as a prompt input once
        # so the full input size is covered
        num_input_tokens += num_tokens

        # A single MAX_CONTEXT_TOKENS worth of output is generated per chunk
        num_output_tokens += num_input_chunks * MAX_CONTEXT_TOKENS

    # going over each doc once means all the tokens, plus the prompt tokens for
    # the summary prompt. This CAN happen even when USE_DOCUMENT_SUMMARY is false,
    # since doc summaries are used for longer documents when USE_CHUNK_SUMMARY is true.
    # So, we include this unconditionally to overestimate.
    num_input_tokens += num_tokens + num_docs * DOCUMENT_SUMMARY_TOKEN_ESTIMATE
    num_output_tokens += num_docs * MAX_CONTEXT_TOKENS

    try:
        usd_per_prompt, usd_per_completion = litellm.cost_per_token(
            model=llm.config.model_name,
            prompt_tokens=num_input_tokens,
            completion_tokens=num_output_tokens,
        )
    except Exception:
        logger.exception(
            "An unexpected error occurred while calculating cost for model "
            f"{llm.config.model_name} (potentially due to malformed name). "
            "Assuming cost is 0."
        )
        return 0

    # Costs are in USD dollars per million tokens
    return usd_per_prompt + usd_per_completion


def get_llm_max_tokens(
    model_map: dict,
    model_name: str,
    model_provider: str,
) -> int:
    """Best effort attempt to get the max tokens for the LLM"""
    if GEN_AI_MAX_TOKENS:
        # This is an override, so always return this
        logger.info(f"Using override GEN_AI_MAX_TOKENS: {GEN_AI_MAX_TOKENS}")
        return GEN_AI_MAX_TOKENS

    try:
        model_obj = find_model_obj(
            model_map,
            model_provider,
            model_name,
        )
        if not model_obj:
            raise RuntimeError(
                f"No litellm entry found for {model_provider}/{model_name}"
            )

        if "max_input_tokens" in model_obj:
            max_tokens = model_obj["max_input_tokens"]
            return max_tokens

        if "max_tokens" in model_obj:
            max_tokens = model_obj["max_tokens"]
            return max_tokens

        logger.error(f"No max tokens found for LLM: {model_name}")
        raise RuntimeError("No max tokens found for LLM")
    except Exception:
        logger.exception(
            f"Failed to get max tokens for LLM with name {model_name}. Defaulting to {GEN_AI_MODEL_FALLBACK_MAX_TOKENS}."
        )
        return GEN_AI_MODEL_FALLBACK_MAX_TOKENS


def get_llm_max_output_tokens(
    model_map: dict,
    model_name: str,
    model_provider: str,
) -> int:
    """Best effort attempt to get the max output tokens for the LLM"""
    try:
        model_obj = model_map.get(f"{model_provider}/{model_name}")
        if not model_obj:
            model_obj = model_map[model_name]
        else:
            pass

        if "max_output_tokens" in model_obj:
            max_output_tokens = model_obj["max_output_tokens"]
            return max_output_tokens

        # Fallback to a fraction of max_tokens if max_output_tokens is not specified
        if "max_tokens" in model_obj:
            max_output_tokens = int(model_obj["max_tokens"] * 0.1)
            return max_output_tokens

        logger.error(f"No max output tokens found for LLM: {model_name}")
        raise RuntimeError("No max output tokens found for LLM")
    except Exception:
        default_output_tokens = int(GEN_AI_MODEL_FALLBACK_MAX_TOKENS)
        logger.exception(
            f"Failed to get max output tokens for LLM with name {model_name}. "
            f"Defaulting to {default_output_tokens} (fallback max tokens)."
        )
        return default_output_tokens


def get_max_input_tokens(
    model_name: str,
    model_provider: str,
    output_tokens: int = GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
) -> int:
    # NOTE: we previously used `litellm.get_max_tokens()`, but despite the name, this actually
    # returns the max OUTPUT tokens. Under the hood, this uses the `litellm.model_cost` dict,
    # and there is no other interface to get what we want. This should be okay though, since the
    # `model_cost` dict is a named public interface:
    # https://litellm.vercel.app/docs/completion/token_usage#7-model_cost
    # model_map is  litellm.model_cost
    litellm_model_map = get_model_map()

    input_toks = (
        get_llm_max_tokens(
            model_name=model_name,
            model_provider=model_provider,
            model_map=litellm_model_map,
        )
        - output_tokens
    )

    if input_toks <= 0:
        return GEN_AI_MODEL_FALLBACK_MAX_TOKENS

    return input_toks


def get_max_input_tokens_from_llm_provider(
    llm_provider: "LLMProviderView",
    model_name: str,
) -> int:
    max_input_tokens = None
    for model_configuration in llm_provider.model_configurations:
        if model_configuration.name == model_name:
            max_input_tokens = model_configuration.max_input_tokens
    return (
        max_input_tokens
        if max_input_tokens
        else get_max_input_tokens(
            model_provider=llm_provider.name,
            model_name=model_name,
        )
    )


def model_supports_image_input(model_name: str, model_provider: str) -> bool:

    # First, try to read an explicit configuration from the model_configuration table
    try:
        with get_session_with_current_tenant() as db_session:
            model_config = db_session.scalar(
                select(ModelConfiguration)
                .join(
                    LLMProvider,
                    ModelConfiguration.llm_provider_id == LLMProvider.id,
                )
                .where(
                    ModelConfiguration.name == model_name,
                    LLMProvider.provider == model_provider,
                )
            )
            if model_config and model_config.supports_image_input is not None:
                return model_config.supports_image_input
    except Exception as e:
        logger.warning(
            f"Failed to query database for {model_provider} model {model_name} image support: {e}"
        )

    # Fallback to looking up the model in the litellm model_cost dict
    try:
        model_obj = find_model_obj(get_model_map(), model_provider, model_name)
        if not model_obj:
            logger.warning(
                f"No litellm entry found for {model_provider}/{model_name}, "
                "this model may or may not support image input."
            )
            return False
        return model_obj.get("supports_vision", False)
    except Exception:
        logger.exception(
            f"Failed to get model object for {model_provider}/{model_name}"
        )
        return False


def model_is_reasoning_model(model_name: str, model_provider: str) -> bool:
    import litellm

    model_map = get_model_map()
    try:
        model_obj = find_model_obj(
            model_map,
            model_provider,
            model_name,
        )
        if model_obj and "supports_reasoning" in model_obj:
            return model_obj["supports_reasoning"]

        # Fallback: try using litellm.supports_reasoning() for newer models
        try:
            logger.debug("Falling back to `litellm.supports_reasoning`")
            full_model_name = (
                f"{model_provider}/{model_name}"
                if model_provider not in model_name
                else model_name
            )
            return litellm.supports_reasoning(model=full_model_name)
        except Exception:
            logger.exception(
                f"Failed to check if {model_provider}/{model_name} supports reasoning"
            )
            return False

    except Exception:
        logger.exception(
            f"Failed to get model object for {model_provider}/{model_name}"
        )
        return False
