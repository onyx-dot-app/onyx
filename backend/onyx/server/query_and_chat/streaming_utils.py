from __future__ import annotations

import re

from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import GeneratedImage
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import Placement
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd


_CANNOT_SHOW_STEP_RESULTS_STR = "[Cannot display step results]"


def _adjust_message_text_for_agent_search_results(
    adjusted_message_text: str, final_documents: list[SavedSearchDoc]
) -> str:
    # Remove all [Q<integer>] patterns (sub-question citations)
    return re.sub(r"\[Q\d+\]", "", adjusted_message_text)


def _replace_d_citations_with_links(
    message_text: str, final_documents: list[SavedSearchDoc]
) -> str:
    def replace_citation(match: re.Match[str]) -> str:
        d_number = match.group(1)
        try:
            doc_index = int(d_number) - 1
            if 0 <= doc_index < len(final_documents):
                doc = final_documents[doc_index]
                link = doc.link if doc.link else ""
                return f"[[{d_number}]]({link})"
            return match.group(0)
        except (ValueError, IndexError):
            return match.group(0)

    return re.sub(r"\[D(\d+)\]", replace_citation, message_text)


def create_message_packets(
    message_text: str,
    final_documents: list[SavedSearchDoc] | None,
    turn_index: int,
    is_legacy_agentic: bool = False,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=AgentResponseStart(
                final_documents=SearchDoc.from_saved_search_docs(final_documents or []),
            ),
        )
    )

    adjusted_message_text = message_text
    if is_legacy_agentic:
        if final_documents is not None:
            adjusted_message_text = _adjust_message_text_for_agent_search_results(
                message_text, final_documents
            )
            adjusted_message_text = _replace_d_citations_with_links(
                adjusted_message_text, final_documents
            )
        else:
            adjusted_message_text = re.sub(r"\[Q\d+\]", "", message_text)

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=AgentResponseDelta(
                content=adjusted_message_text,
            ),
        ),
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=SectionEnd(),
        )
    )

    return packets


def create_citation_packets(
    citation_info_list: list[CitationInfo], turn_index: int
) -> list[Packet]:
    packets: list[Packet] = []

    # Emit each citation as a separate CitationInfo packet
    for citation_info in citation_info_list:
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index),
                obj=citation_info,
            )
        )

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets


def create_reasoning_packets(reasoning_text: str, turn_index: int) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(placement=Placement(turn_index=turn_index), obj=ReasoningStart())
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=ReasoningDelta(
                reasoning=reasoning_text,
            ),
        ),
    )

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets


def create_image_generation_packets(
    images: list[GeneratedImage], turn_index: int
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=ImageGenerationToolStart(),
        )
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=ImageGenerationFinal(images=images),
        ),
    )

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets


def create_custom_tool_packets(
    tool_name: str,
    response_type: str,
    turn_index: int,
    data: dict | list | str | int | float | bool | None = None,
    file_ids: list[str] | None = None,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=CustomToolStart(tool_name=tool_name),
        )
    )

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=CustomToolDelta(
                tool_name=tool_name,
                response_type=response_type,
                data=data,
                file_ids=file_ids,
            ),
        ),
    )

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets


def create_fetch_packets(
    fetch_docs: list[SavedSearchDoc],
    urls: list[str],
    turn_index: int,
) -> list[Packet]:
    packets: list[Packet] = []
    # Emit start packet
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=OpenUrlStart(),
        )
    )
    # Emit URLs packet
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=OpenUrlUrls(urls=urls),
        )
    )
    # Emit documents packet
    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=OpenUrlDocuments(
                documents=SearchDoc.from_saved_search_docs(fetch_docs)
            ),
        )
    )
    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))
    return packets


def create_search_packets(
    search_queries: list[str],
    saved_search_docs: list[SavedSearchDoc],
    is_internet_search: bool,
    turn_index: int,
) -> list[Packet]:
    packets: list[Packet] = []

    packets.append(
        Packet(
            placement=Placement(turn_index=turn_index),
            obj=SearchToolStart(
                is_internet_search=is_internet_search,
            ),
        )
    )

    # Emit queries if present
    if search_queries:
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index),
                obj=SearchToolQueriesDelta(queries=search_queries),
            ),
        )

    # Emit documents if present
    if saved_search_docs:
        packets.append(
            Packet(
                placement=Placement(turn_index=turn_index),
                obj=SearchToolDocumentsDelta(
                    documents=SearchDoc.from_saved_search_docs(saved_search_docs)
                ),
            ),
        )

    packets.append(Packet(placement=Placement(turn_index=turn_index), obj=SectionEnd()))

    return packets
