"""
Temporary translation layer between run_llm_loop packet format and frontend-expected packet format.

This translation function sits between the backend packet generation and frontend consumption,
translating from the new backend format to the old frontend-expected format.
"""

from collections.abc import Generator
from typing import Any
from typing import Literal

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
        message_id: The message ID (not used for ind, only for reference)

    Yields:
        Translated packet dictionaries ready for frontend consumption

    Translation notes:
        - Packet structure: {turn_index, tab_index, obj} → {ind, obj}
        - CRITICAL: Each packet's turn_index becomes its ind (different sections use different ind values!)
        - MessageStart: Add id, content fields, preserve final_documents
        - SearchTool: search_tool_start → internal_search_tool_start
        - SearchTool: Combine queries + documents → internal_search_tool_delta
        - ReasoningDone → reasoning_end (kept as separate packet in old format)
        - CitationInfo → Accumulate and emit as CitationStart + CitationDelta
        - Add SectionEnd packets after tool completions
    """
    # Track search tool state
    search_tool_active = False
    # search_tool_turn_index: int | None = None

    # Track citations to batch them (emitted AFTER message with different ind)
    accumulated_citations: list[dict[str, Any]] = []

    # Track the last seen turn_index for sections
    last_turn_index = 0

    for packet in packet_stream:
        obj = packet.obj
        # Use the packet's turn_index as the ind (CRITICAL!)
        turn_index = (
            packet.turn_index if packet.turn_index is not None else last_turn_index
        )
        last_turn_index = turn_index

        # Translate AgentResponseStart (message_start)
        if isinstance(obj, AgentResponseStart):
            # Old format expects: id (string), content (string), final_documents
            translated_obj = {
                "type": "message_start",
                "id": str(message_id),  # Keep message_id for the id field
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
                "ind": turn_index,  # Use packet's turn_index as ind
                "obj": translated_obj,
            }
            continue

        # Translate AgentResponseDelta (message_delta) - pass through
        # DO NOT emit section_end between message_start and message_delta!
        if isinstance(obj, AgentResponseDelta):
            yield {
                "ind": turn_index,
                "obj": {
                    "type": "message_delta",
                    "content": obj.content,
                },
            }
            continue

        # Translate SearchToolStart
        if isinstance(obj, SearchToolStart):
            search_tool_active = True
            # search_tool_turn_index = turn_index  # Save turn_index for this tool

            yield {
                "ind": turn_index,
                "obj": {
                    "type": "internal_search_tool_start",
                    "is_internet_search": getattr(obj, "is_internet_search", False),
                },
            }
            continue

        # Emit SearchToolQueriesDelta immediately with empty documents
        if isinstance(obj, SearchToolQueriesDelta):
            yield {
                "ind": turn_index,
                "obj": {
                    "type": "internal_search_tool_delta",
                    "queries": obj.queries if obj.queries else [],
                    "documents": [],  # Empty documents array
                },
            }
            continue

        # Emit SearchToolDocumentsDelta immediately with empty queries
        if isinstance(obj, SearchToolDocumentsDelta):
            yield {
                "ind": turn_index,
                "obj": {
                    "type": "internal_search_tool_delta",
                    "queries": [],  # Empty queries array
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

            # Emit section_end for search tool after documents
            yield {
                "ind": turn_index,
                "obj": {"type": "section_end"},
            }

            search_tool_active = False
            continue

        # Translate ReasoningStart
        if isinstance(obj, ReasoningStart):
            yield {
                "ind": turn_index,
                "obj": {"type": "reasoning_start"},
            }
            continue

        # Translate ReasoningDelta - pass through
        if isinstance(obj, ReasoningDelta):
            yield {
                "ind": turn_index,
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
                "ind": turn_index,
                "obj": {"type": "section_end"},
            }
            continue

        # Accumulate CitationInfo packets (emitted individually in new backend, batched in old)
        if isinstance(obj, CitationInfo):
            accumulated_citations.append(
                {
                    "citation_num": obj.citation_number,
                    "document_id": obj.document_id,
                }
            )
            # Don't yield anything yet - citations are batched at the end
            continue

        # Translate ImageGenerationToolStart
        if isinstance(obj, ImageGenerationToolStart):
            yield {
                "ind": turn_index,
                "obj": {"type": "image_generation_tool_start"},
            }
            continue

        # Translate ImageGenerationFinal
        if isinstance(obj, ImageGenerationFinal):
            yield {
                "ind": turn_index,
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
                "ind": turn_index,
                "obj": {"type": "section_end"},
            }
            continue

        # Translate OpenUrl to fetch_tool_start
        if isinstance(obj, OpenUrl):
            yield {
                "ind": turn_index,
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
                "ind": turn_index,
                "obj": {"type": "section_end"},
            }
            continue

        # Translate CustomToolStart
        if isinstance(obj, CustomToolStart):
            yield {
                "ind": turn_index,
                "obj": {
                    "type": "custom_tool_start",
                    "tool_name": obj.tool_name,
                },
            }
            continue

        # Translate CustomToolDelta
        if isinstance(obj, CustomToolDelta):
            yield {
                "ind": turn_index,
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
                "ind": turn_index,
                "obj": {"type": "section_end"},
            }
            continue

        # Translate OverallStop
        if isinstance(obj, OverallStop):
            # First emit section_end to close the message section
            # (Frontend looks for SECTION_END to determine if final answer is complete)
            yield {
                "ind": turn_index,
                "obj": {"type": "section_end"},
            }

            # Then emit any accumulated citations AFTER the message
            # Citations use a DIFFERENT ind (turn_index + 1) to separate them from the message
            has_citations = len(accumulated_citations) > 0
            if has_citations:
                citation_ind = turn_index + 1

                yield {
                    "ind": citation_ind,
                    "obj": {"type": "citation_start"},
                }

                yield {
                    "ind": citation_ind,
                    "obj": {
                        "type": "citation_delta",
                        "citations": accumulated_citations,
                    },
                }

                yield {
                    "ind": citation_ind,
                    "obj": {"type": "section_end"},
                }

            # Finally emit stop with the last ind used
            yield {
                "ind": turn_index + 1 if has_citations else turn_index,
                "obj": {"type": "stop"},
            }
            # Don't continue - we want to exit the loop after stop
            return

        # For any other packet types, try to pass through
        if hasattr(obj, "model_dump"):
            yield {
                "ind": turn_index,
                "obj": obj.model_dump(),
            }
        else:
            yield {
                "ind": turn_index,
                "obj": obj,
            }

    # Handle any incomplete sections at end of stream (in case stream ended without OverallStop)
    if search_tool_active:
        # If search tool was active but never closed, emit section_end
        yield {
            "ind": last_turn_index,
            "obj": {"type": "section_end"},
        }

    # Emit any remaining citations before final stop (in case stream ended without OverallStop)
    has_citations = len(accumulated_citations) > 0
    if has_citations:
        citation_ind = last_turn_index + 1

        yield {
            "ind": citation_ind,
            "obj": {"type": "citation_start"},
        }

        yield {
            "ind": citation_ind,
            "obj": {
                "type": "citation_delta",
                "citations": accumulated_citations,
            },
        }

        yield {
            "ind": citation_ind,
            "obj": {"type": "section_end"},
        }

    # Emit final stop packet (only if we didn't already return from OverallStop)
    yield {
        "ind": last_turn_index + 1 if has_citations else last_turn_index,
        "obj": {"type": "stop"},
    }
