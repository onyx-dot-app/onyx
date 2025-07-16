from datetime import datetime
from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import api_key_dep
from onyx.chat.models import AnswerStyleConfig, LlmDoc
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.prompts.prompt_utils import clean_up_source
from onyx.llm.factory import get_default_llms
from onyx.tools.models import SearchToolOverrideKwargs, ToolResponse
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/onyx-tools")


class SearchToolRequest(BaseModel):
    query: str
    time_cutoff: datetime | None = None
    document_sources: list[DocumentSource] | None = None


class FoundDocSearchTool(BaseModel):
    title: str
    source_type: str
    content: str
    updated_at: datetime | None = None
    link: str | None = None


@router.post("/search-tool")
def search_tool_endpoint(
    request: SearchToolRequest,
    search_user: User | None = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> list[FoundDocSearchTool]:
    """
    Endpoint that exposes the SearchTool.run() method for MCP server integration.

    This endpoint initializes a SearchTool instance and runs a search query,
    returning the final context documents as structured results.
    """
    logger.info(f"Received SearchTool request with query: {request=}")

    # Get default LLMs
    primary_llm, fast_llm = get_default_llms()

    # Get default persona (id=0)
    persona = get_persona_by_id(0, None, db_session)

    # Set up configurations
    retrieval_options = RetrievalDetails()
    prompt_config = PromptConfig.from_model(persona.prompts[0])
    pruning_config = DocumentPruningConfig()
    answer_style_config = AnswerStyleConfig(citation_config=CitationConfig())
    evaluation_type = LLMEvaluationType.SKIP

    # Create SearchTool instance
    search_tool = SearchTool(
        db_session=db_session,
        user=search_user,
        persona=persona,
        retrieval_options=retrieval_options,
        prompt_config=prompt_config,
        llm=primary_llm,
        fast_llm=fast_llm,
        document_pruning_config=pruning_config,
        answer_style_config=answer_style_config,
        evaluation_type=evaluation_type,
    )

    # Prepare override kwargs for filtering
    override_kwargs = None
    if request.time_cutoff or request.document_sources:
        override_kwargs = SearchToolOverrideKwargs(
            time_cutoff=request.time_cutoff,
            document_sources=request.document_sources
        )

    # Run the search
    results = []
    try:
        for response in search_tool.run(override_kwargs=override_kwargs, query=request.query):
            results.append(response)

        # Extract the final context documents
        final_docs_response: ToolResponse | None = next((response for response in results if response.id == FINAL_CONTEXT_DOCUMENTS_ID), None)

        if final_docs_response:
            # Extract document information for structured response
            llm_docs: list[LlmDoc] = final_docs_response.response
            found_docs = [
                FoundDocSearchTool(
                        title=doc.semantic_identifier,
                        source_type=clean_up_source(doc.source_type),
                        content=doc.content.strip(),
                        updated_at=doc.updated_at,
                        link=doc.link
                    ) for doc in llm_docs
            ]
            return found_docs
        else:
            logger.warning("No final context documents found in search results")
            return []

    except Exception as e:
        logger.error(f"Error running SearchTool: {str(e)}", exc_info=True)
        return []
