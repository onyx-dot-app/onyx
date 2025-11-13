# from datetime import datetime
# from typing import cast

# from onyx.chat.models import LlmDoc
# from onyx.configs.constants import DocumentSource
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
# ) -> list[LlmDoc]:
#     # new db session to avoid concurrency issues

#     retrieved_docs: list[LlmDoc] = []

#     for tool_response in search_tool.run(
#         query=question,
#         override_kwargs=SearchToolOverrideKwargs(original_query=question),
#     ):
#         # get retrieved docs to send to the rest of the graph
#         if tool_response.id == FINAL_CONTEXT_DOCUMENTS_ID:
#             retrieved_docs = cast(list[LlmDoc], tool_response.response)[:10]
#             break
#     return retrieved_docs


# def extract_section(
#     text: str, start_marker: str, end_marker: str | None = None
# ) -> str | None:
#     """Extract text between markers, returning None if markers not found"""
#     parts = text.split(start_marker)

#     if len(parts) == 1:
#         return None

#     after_start = parts[1].strip()

#     if not end_marker:
#         return after_start

#     extract = after_start.split(end_marker)[0]

#     return extract.strip()
