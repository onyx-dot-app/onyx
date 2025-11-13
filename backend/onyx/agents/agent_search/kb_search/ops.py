# from datetime import datetime
# from typing import cast

# from onyx.chat.models import LlmDoc
# from onyx.configs.constants import DocumentSource
# from onyx.configs.kg_configs import KG_RESEARCH_NUM_RETRIEVED_DOCS
# from onyx.context.search.models import InferenceSection
# from onyx.tools.models import SearchToolOverrideKwargs
# from onyx.tools.tool_implementations.search.search_tool import (
#     FINAL_CONTEXT_DOCUMENTS_ID,
# )
# from onyx.tools.tool_implementations.search.search_tool import SearchTool


# def research(
#     question: str,
#     search_tool: SearchTool,
#     document_sources: list[DocumentSource] | None = None,
#     time_cutoff: datetime | None = None,
#     kg_entities: list[str] | None = None,
#     kg_relationships: list[str] | None = None,
#     kg_terms: list[str] | None = None,
#     kg_sources: list[str] | None = None,
#     kg_chunk_id_zero_only: bool = False,
#     inference_sections_only: bool = False,
# ) -> list[LlmDoc] | list[InferenceSection]:
#     # new db session to avoid concurrency issues

#     retrieved_docs: list[LlmDoc] | list[InferenceSection] = []

#     for tool_response in search_tool.run(
#         query=question,
#         override_kwargs=SearchToolOverrideKwargs(original_query=question),
#     ):
#         if inference_sections_only and tool_response.id == "search_response_summary":
#             retrieved_docs = tool_response.response.top_sections[
#                 :KG_RESEARCH_NUM_RETRIEVED_DOCS
#             ]
#             retrieved_docs = cast(list[InferenceSection], retrieved_docs)
#             break
#         # get retrieved docs to send to the rest of the graph
#         elif tool_response.id == FINAL_CONTEXT_DOCUMENTS_ID:
#             retrieved_docs = cast(list[LlmDoc], tool_response.response)[
#                 :KG_RESEARCH_NUM_RETRIEVED_DOCS
#             ]
#             break
#     return retrieved_docs
