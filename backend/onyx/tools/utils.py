import json

import litellm
from sqlalchemy.orm import Session

from onyx.configs.app_configs import AZURE_DALLE_API_KEY
from onyx.db.connector import check_connectors_exist
from onyx.db.document import check_docs_exist
from onyx.db.models import LLMProvider
from onyx.llm.llm_provider_options import ANTHROPIC_PROVIDER_NAME
from onyx.llm.llm_provider_options import BEDROCK_PROVIDER_NAME
from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.tools.tool import Tool


def explicit_tool_calling_supported(model_provider: str, model_name: str) -> bool:
    model_map = get_model_map()
    model_obj = find_model_obj(
        model_map=model_map,
        provider=model_provider,
        model_name=model_name,
    )

    model_supports = (
        model_obj.get("supports_function_calling", False) if model_obj else False
    )
    # Anthropic models support tool calling, but
    # a) will raise an error if you provide any tool messages and don't provide a list of tools.
    # b) will send text before and after generating tool calls.
    # We don't want to provide that list of tools because our UI doesn't support sequential
    # tool calling yet for (a) and just looks bad for (b), so for now we just treat anthropic
    # models as non-tool-calling.
    return (
        model_supports
        and model_provider != ANTHROPIC_PROVIDER_NAME
        and model_name not in litellm.anthropic_models
        and (
            model_provider != BEDROCK_PROVIDER_NAME
            or not any(name in model_name for name in litellm.anthropic_models)
        )
    )


def compute_tool_tokens(tool: Tool, llm_tokenizer: BaseTokenizer) -> int:
    return len(llm_tokenizer.encode(json.dumps(tool.tool_definition())))


def compute_all_tool_tokens(tools: list[Tool], llm_tokenizer: BaseTokenizer) -> int:
    return sum(compute_tool_tokens(tool, llm_tokenizer) for tool in tools)


def is_image_generation_available(db_session: Session) -> bool:
    providers = db_session.query(LLMProvider).all()
    for provider in providers:
        if provider.provider == "openai":
            return True

    return bool(AZURE_DALLE_API_KEY)


def is_document_search_available(db_session: Session) -> bool:
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    return docs_exist or connectors_exist
