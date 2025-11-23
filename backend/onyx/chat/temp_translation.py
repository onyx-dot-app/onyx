"""
Temporary translation layer between run_llm_loop packet format and frontend-expected packet format.

This translation function sits between the backend packet generation and frontend consumption,
translating from the new backend format to the old frontend-expected format.
"""

from collections.abc import Generator
from typing import Any
from typing import Literal

from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import BaseObj
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import OpenUrl
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart


class SectionEnd(BaseObj):
    type: Literal["section_end"] = "section_end"


def translate_llm_loop_packets(
    packet_stream: Generator[Packet, None, None],
    message_id: int,
) -> Generator[dict[str, Any], None, None]:
    """
    Translates packets from run_llm_loop to frontend-expected format.

    Args:
        packet_stream: Generator yielding packets from run_llm_loop
        message_id: The message ID to use as 'ind' in frontend

    Yields:
        Translated packet dictionaries ready for frontend consumption

    Translation notes:
        - Packet structure: {turn_index, tab_index, obj} → {ind, obj}
        - MessageStart: Add id, content fields, preserve final_documents
        - SearchTool: search_tool_start → internal_search_tool_start
        - SearchTool: Combine queries + documents → internal_search_tool_delta
        - ReasoningDone → reasoning_end (kept as separate packet in old format)
        - CitationInfo → Accumulate and emit as CitationStart + CitationDelta
        - Add SectionEnd packets after tool completions
    """
    # Track search tool state to combine queries and documents
    search_tool_active = False
    accumulated_queries: list[str] | None = None
    accumulated_documents: list[SearchDoc] | None = None

    # Track citations to batch them
    accumulated_citations: list[dict[str, Any]] = []
    citation_section_active = False

    # Track reasoning state
    # Track if we've seen AgentResponseStart but not yet the first AgentResponseDelta
    answer_started = False
    first_answer_delta_emitted = False

    for packet in packet_stream:
        obj = packet.obj

        # Translate AgentResponseStart (message_start)
        if isinstance(obj, AgentResponseStart):
            answer_started = True
            # Old format expects: id (string), content (string), final_documents
            translated_obj = {
                "type": "message_start",
                "id": str(message_id),  # Add id field
                "content": "",  # Initial content is empty
                "final_documents": None,  # Will be set if available
            }

            # Check if final_documents exists in the object
            if hasattr(obj, "final_documents") and obj.final_documents:
                translated_obj["final_documents"] = [
                    doc.model_dump() if hasattr(doc, "model_dump") else doc
                    for doc in obj.final_documents
                ]

            yield {
                "ind": message_id,
                "obj": translated_obj,
            }
            continue

        # Translate AgentResponseDelta (message_delta) - pass through
        if isinstance(obj, AgentResponseDelta):
            # Emit section_end before the first answer delta to mark end of preparation phase
            if answer_started and not first_answer_delta_emitted:
                yield {
                    "ind": message_id,
                    "obj": {"type": "section_end"},
                }
                first_answer_delta_emitted = True

            yield {
                "ind": message_id,
                "obj": {
                    "type": "message_delta",
                    "content": obj.content,
                },
            }
            continue

        # Translate SearchToolStart
        if isinstance(obj, SearchToolStart):
            search_tool_active = True
            accumulated_queries = None
            accumulated_documents = None

            yield {
                "ind": message_id,
                "obj": {
                    "type": "internal_search_tool_start",
                    "is_internet_search": getattr(obj, "is_internet_search", False),
                },
            }
            continue

        # Accumulate SearchToolQueriesDelta
        if isinstance(obj, SearchToolQueriesDelta):
            accumulated_queries = obj.queries
            continue

        # Accumulate SearchToolDocumentsDelta and emit combined delta
        if isinstance(obj, SearchToolDocumentsDelta):
            accumulated_documents = obj.documents

            # Emit combined search tool delta
            yield {
                "ind": message_id,
                "obj": {
                    "type": "internal_search_tool_delta",
                    "queries": accumulated_queries if accumulated_queries else [],
                    "documents": (
                        [
                            doc.model_dump() if hasattr(doc, "model_dump") else doc
                            for doc in accumulated_documents
                        ]
                        if accumulated_documents
                        else []
                    ),
                },
            }

            # Emit section_end for search tool
            yield {
                "ind": message_id,
                "obj": {"type": "section_end"},
            }

            search_tool_active = False
            accumulated_queries = None
            accumulated_documents = None
            continue

        # Translate ReasoningStart
        if isinstance(obj, ReasoningStart):
            yield {
                "ind": message_id,
                "obj": {"type": "reasoning_start"},
            }
            continue

        # Translate ReasoningDelta - pass through
        if isinstance(obj, ReasoningDelta):
            yield {
                "ind": message_id,
                "obj": {
                    "type": "reasoning_delta",
                    "reasoning": obj.reasoning,
                },
            }
            continue

        # Translate ReasoningDone to reasoning_end
        if isinstance(obj, ReasoningDone):
            pass
            # Old format doesn't have a reasoning_end packet type, just emit section_end
            yield {
                "ind": message_id,
                "obj": {"type": "section_end"},
            }
            continue

        # Accumulate CitationInfo packets
        if isinstance(obj, CitationInfo):
            if not citation_section_active:
                # Emit citation_start when first citation arrives
                yield {
                    "ind": message_id,
                    "obj": {"type": "citation_start"},
                }
                citation_section_active = True

            accumulated_citations.append(
                {
                    "citation_num": obj.citation_number,
                    "document_id": obj.document_id,
                    "level": None,  # Old format had level for sub-questions
                    "level_question_num": None,
                }
            )
            continue

        # Translate ImageGenerationToolStart
        if isinstance(obj, ImageGenerationToolStart):
            yield {
                "ind": message_id,
                "obj": {"type": "image_generation_tool_start"},
            }
            continue

        # Translate ImageGenerationFinal
        if isinstance(obj, ImageGenerationFinal):
            yield {
                "ind": message_id,
                "obj": {
                    "type": "image_generation_tool_delta",
                    "images": [
                        img.model_dump() if hasattr(img, "model_dump") else img
                        for img in obj.images
                    ],
                },
            }

            # Emit section_end for image generation
            yield {
                "ind": message_id,
                "obj": {"type": "section_end"},
            }
            continue

        # Translate OpenUrl to fetch_tool_start
        if isinstance(obj, OpenUrl):
            yield {
                "ind": message_id,
                "obj": {
                    "type": "fetch_tool_start",
                    "documents": (
                        [
                            doc.model_dump() if hasattr(doc, "model_dump") else doc
                            for doc in obj.documents
                        ]
                        if obj.documents
                        else []
                    ),
                },
            }

            # Emit section_end for fetch tool
            yield {
                "ind": message_id,
                "obj": {"type": "section_end"},
            }
            continue

        # Translate CustomToolStart
        if isinstance(obj, CustomToolStart):
            yield {
                "ind": message_id,
                "obj": {
                    "type": "custom_tool_start",
                    "tool_name": obj.tool_name,
                },
            }
            continue

        # Translate CustomToolDelta
        if isinstance(obj, CustomToolDelta):
            yield {
                "ind": message_id,
                "obj": {
                    "type": "custom_tool_delta",
                    "tool_name": obj.tool_name,
                    "response_type": obj.response_type,
                    "data": obj.data,
                    "file_ids": obj.file_ids,
                },
            }

            # Emit section_end for custom tool
            yield {
                "ind": message_id,
                "obj": {"type": "section_end"},
            }
            continue

        # Translate OverallStop
        if isinstance(obj, OverallStop):
            # Before emitting stop, emit any accumulated citations
            if accumulated_citations:
                yield {
                    "ind": message_id,
                    "obj": {
                        "type": "citation_delta",
                        "citations": accumulated_citations,
                    },
                }

                yield {
                    "ind": message_id,
                    "obj": {"type": "section_end"},
                }

                accumulated_citations = []
                citation_section_active = False

            yield {
                "ind": message_id,
                "obj": {"type": "stop"},
            }
            continue

        # For any other packet types, try to pass through
        if hasattr(obj, "model_dump"):
            yield {
                "ind": message_id,
                "obj": obj.model_dump(),
            }
        else:
            yield {
                "ind": message_id,
                "obj": obj,
            }

    # Handle any incomplete sections at end of stream
    if search_tool_active and (accumulated_queries or accumulated_documents):
        yield {
            "ind": message_id,
            "obj": {
                "type": "internal_search_tool_delta",
                "queries": accumulated_queries if accumulated_queries else [],
                "documents": (
                    [
                        doc.model_dump() if hasattr(doc, "model_dump") else doc
                        for doc in accumulated_documents
                    ]
                    if accumulated_documents
                    else []
                ),
            },
        }

        yield {
            "ind": message_id,
            "obj": {"type": "section_end"},
        }

    # Emit any remaining citations before final stop
    if accumulated_citations:
        yield {
            "ind": message_id,
            "obj": {
                "type": "citation_delta",
                "citations": accumulated_citations,
            },
        }

        yield {
            "ind": message_id,
            "obj": {"type": "section_end"},
        }

    # Emit final stop packet if not already emitted
    yield {
        "ind": message_id,
        "obj": {"type": "stop"},
    }
