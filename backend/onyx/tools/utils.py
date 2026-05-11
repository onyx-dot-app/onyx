import json
import re

from sqlalchemy.orm import Session

from onyx.configs.app_configs import AZURE_IMAGE_API_KEY
from onyx.db.connector import check_connectors_exist
from onyx.db.document import check_docs_exist
from onyx.db.models import LLMProvider
from onyx.llm.constants import LlmProviderNames
from onyx.llm.utils import find_model_obj
from onyx.llm.utils import get_model_map
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.tools.interface import Tool

_INVALID_TOOL_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def sanitize_tool_name(name: str) -> str:
    # Bedrock rejects toolUse.name values that don't match [a-zA-Z0-9_-]+, and
    # OpenAI imposes the same constraint on function names. User-supplied
    # Tool.name and OpenAPI operationId can contain spaces, dots, etc. — replace
    # anything outside the allowed set with an underscore so the value is safe
    # to send in tool definitions and in message-history toolUse blocks.
    return _INVALID_TOOL_NAME_CHARS.sub("_", name)


def explicit_tool_calling_supported(model_provider: str, model_name: str) -> bool:
    model_map = get_model_map()
    model_obj = find_model_obj(
        model_map=model_map,
        provider=model_provider,
        model_name=model_name,
    )

    if not model_obj:
        return False
    return bool(model_obj.get("supports_function_calling"))


def compute_tool_tokens(tool: Tool, llm_tokenizer: BaseTokenizer) -> int:
    return len(llm_tokenizer.encode(json.dumps(tool.tool_definition())))


def compute_all_tool_tokens(tools: list[Tool], llm_tokenizer: BaseTokenizer) -> int:
    return sum(compute_tool_tokens(tool, llm_tokenizer) for tool in tools)


def is_image_generation_available(db_session: Session) -> bool:
    providers = db_session.query(LLMProvider).all()
    for provider in providers:
        if provider.provider == LlmProviderNames.OPENAI:
            return True

    return bool(AZURE_IMAGE_API_KEY)


def is_document_search_available(db_session: Session) -> bool:
    docs_exist = check_docs_exist(db_session)
    connectors_exist = check_connectors_exist(db_session)
    return docs_exist or connectors_exist


def generate_tools_description(tools: list[Tool]) -> str:
    if not tools:
        return ""
    if len(tools) == 1:
        return tools[0].name
    if len(tools) == 2:
        return f"{tools[0].name} and {tools[1].name}"

    names = [tool.name for tool in tools[:-1]]
    return ", ".join(names) + f", and {tools[-1].name}"
