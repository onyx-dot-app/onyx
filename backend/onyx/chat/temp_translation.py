"""
Temporary translation layer between run_llm_loop packet format and frontend-expected packet format.

This translation function sits between the backend packet generation and frontend consumption,
translating from the new backend format to the old frontend-expected format.
"""

from collections.abc import Generator
from typing import Any

from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
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
            translated_obj: dict[str, Any] = {
                "type": "message_start",
                "content": "",  # Initial content is empty
                "final_documents": [],  # Will be set if available
            }

            # Check if final_documents exists in the object
            if hasattr(obj, "final_documents") and obj.final_documents:
                translated_obj["final_documents"] = [
                    doc.model_dump() if hasattr(doc, "model_dump") else dict(doc)
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


def translate_session_packets_to_frontend(
    packets: list[Packet],
) -> list[dict[str, Any]]:
    """
    Translates packets from session_loading (new format) to frontend-expected format.

    This is used when replaying saved messages from the database. The packets are
    already created in the new format by translate_assistant_message_to_packets,
    and need to be converted to the old frontend format.

    Args:
        packets: List of Packet objects from session_loading

    Returns:
        List of translated packet dictionaries ready for frontend consumption

    Translation notes:
        - Packet structure: {turn_index, obj} → {ind, obj}
        - AgentResponseStart → message_start with id, content fields
        - AgentResponseDelta → message_delta
        - SearchToolStart → internal_search_tool_start
        - SearchToolQueriesDelta → internal_search_tool_delta (with empty documents)
        - SearchToolDocumentsDelta → internal_search_tool_delta (with empty queries)
        - CitationInfo → Accumulate and emit as citation_start + citation_delta
        - OpenUrl → fetch_tool_start
        - SectionEnd packets are passed through
    """
    from onyx.server.query_and_chat.streaming_models import SectionEnd

    result: list[dict[str, Any]] = []

    # Track citations to batch them
    accumulated_citations: list[dict[str, Any]] = []
    citation_turn_index: int | None = None

    # Track the last seen turn_index
    last_turn_index = 0

    for packet in packets:
        obj = packet.obj
        turn_index = (
            packet.turn_index if packet.turn_index is not None else last_turn_index
        )
        last_turn_index = turn_index

        # Translate AgentResponseStart (message_start)
        if isinstance(obj, AgentResponseStart):
            translated_obj: dict[str, Any] = {
                "type": "message_start",
                "content": "",
                "final_documents": [],
            }

            if hasattr(obj, "final_documents") and obj.final_documents:
                translated_obj["final_documents"] = [
                    doc.model_dump() if hasattr(doc, "model_dump") else doc
                    for doc in obj.final_documents
                ]

            result.append(
                {
                    "ind": turn_index,
                    "obj": translated_obj,
                }
            )
            continue

        # Translate AgentResponseDelta (message_delta)
        if isinstance(obj, AgentResponseDelta):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "message_delta",
                        "content": obj.content,
                    },
                }
            )
            continue

        # Translate SearchToolStart
        if isinstance(obj, SearchToolStart):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "internal_search_tool_start",
                        "is_internet_search": getattr(obj, "is_internet_search", False),
                    },
                }
            )
            continue

        # Translate SearchToolQueriesDelta
        if isinstance(obj, SearchToolQueriesDelta):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "internal_search_tool_delta",
                        "queries": obj.queries if obj.queries else [],
                        "documents": [],
                    },
                }
            )
            continue

        # Translate SearchToolDocumentsDelta
        if isinstance(obj, SearchToolDocumentsDelta):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "internal_search_tool_delta",
                        "queries": [],
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
            )
            continue

        # Translate ReasoningStart
        if isinstance(obj, ReasoningStart):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {"type": "reasoning_start"},
                }
            )
            continue

        # Translate ReasoningDelta
        if isinstance(obj, ReasoningDelta):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "reasoning_delta",
                        "reasoning": obj.reasoning,
                    },
                }
            )
            continue

        # Translate ReasoningDone
        if isinstance(obj, ReasoningDone):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {"type": "section_end"},
                }
            )
            continue

        # Accumulate CitationInfo packets
        if isinstance(obj, CitationInfo):
            accumulated_citations.append(
                {
                    "citation_num": obj.citation_number,
                    "document_id": obj.document_id,
                }
            )
            citation_turn_index = turn_index
            continue

        # Translate ImageGenerationToolStart
        if isinstance(obj, ImageGenerationToolStart):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {"type": "image_generation_tool_start"},
                }
            )
            continue

        # Translate ImageGenerationFinal
        if isinstance(obj, ImageGenerationFinal):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "image_generation_tool_delta",
                        "images": [
                            img.model_dump() if hasattr(img, "model_dump") else img
                            for img in obj.images
                        ],
                    },
                }
            )
            continue

        # Translate OpenUrl to fetch_tool_start
        if isinstance(obj, OpenUrl):
            result.append(
                {
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
            )
            continue

        # Translate CustomToolStart
        if isinstance(obj, CustomToolStart):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "custom_tool_start",
                        "tool_name": obj.tool_name,
                    },
                }
            )
            continue

        # Translate CustomToolDelta
        if isinstance(obj, CustomToolDelta):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {
                        "type": "custom_tool_delta",
                        "tool_name": obj.tool_name,
                        "response_type": obj.response_type,
                        "data": obj.data,
                        "file_ids": obj.file_ids,
                    },
                }
            )
            continue

        # Pass through SectionEnd
        if isinstance(obj, SectionEnd):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {"type": "section_end"},
                }
            )
            continue

        # Translate OverallStop
        if isinstance(obj, OverallStop):
            result.append(
                {
                    "ind": turn_index,
                    "obj": {"type": "stop"},
                }
            )
            continue

        # For any other packet types, try to pass through
        if hasattr(obj, "model_dump"):
            result.append(
                {
                    "ind": turn_index,
                    "obj": obj.model_dump(),
                }
            )
        else:
            result.append(
                {
                    "ind": turn_index,
                    "obj": obj,  # type: ignore
                }
            )

    # Emit accumulated citations at the end (if any)
    if accumulated_citations:
        ind = (
            citation_turn_index if citation_turn_index is not None else last_turn_index
        )

        result.append(
            {
                "ind": ind,
                "obj": {"type": "citation_start"},
            }
        )

        result.append(
            {
                "ind": ind,
                "obj": {
                    "type": "citation_delta",
                    "citations": accumulated_citations,
                },
            }
        )

        result.append(
            {
                "ind": ind,
                "obj": {"type": "section_end"},
            }
        )

    return result
