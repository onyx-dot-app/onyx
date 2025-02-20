import json

from sqlalchemy.orm import Session

from onyx.configs.app_configs import AZURE_DALLE_API_KEY
from onyx.db.connector import check_connectors_exist
from onyx.db.document import check_docs_exist
from onyx.db.models import LLMProvider
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.tools.tool import Tool


OPEN_AI_TOOL_CALLING_MODELS = {
    "gpt-3.5-turbo",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-4o",
    "gpt-4o-mini",
}


def explicit_tool_calling_supported(model_provider: str, model_name: str) -> bool:
    return model_provider == "openai" and model_name in OPEN_AI_TOOL_CALLING_MODELS


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
