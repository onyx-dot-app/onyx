from __future__ import annotations

from typing import cast

from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import CreateChatSessionID
from onyx.chat.models import MessageResponseIDInfo
from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import ImageGenerationFinal
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta


def assert_answer_stream_part_correct(
    received: AnswerStreamPart, expected: AnswerStreamPart
) -> None:
    assert isinstance(received, type(expected))

    if isinstance(received, Packet):
        r_packet = cast(Packet, received)
        e_packet = cast(Packet, expected)

        assert r_packet.placement == e_packet.placement

        if isinstance(r_packet.obj, SearchToolDocumentsDelta):
            assert isinstance(e_packet.obj, SearchToolDocumentsDelta)
            assert is_search_tool_document_delta_equal(r_packet.obj, e_packet.obj)
            return
        elif isinstance(r_packet.obj, OpenUrlDocuments):
            assert isinstance(e_packet.obj, OpenUrlDocuments)
            assert is_open_url_documents_equal(r_packet.obj, e_packet.obj)
            return
        elif isinstance(r_packet.obj, AgentResponseStart):
            assert isinstance(e_packet.obj, AgentResponseStart)
            assert is_agent_response_start_equal(r_packet.obj, e_packet.obj)
            return
        elif isinstance(r_packet.obj, ImageGenerationFinal):
            assert isinstance(e_packet.obj, ImageGenerationFinal)
            assert is_image_generation_final_equal(r_packet.obj, e_packet.obj)
            return

        assert r_packet.obj == e_packet.obj
    elif isinstance(received, MessageResponseIDInfo):
        # We're not going to make assumptions about what the user id / assistant id should be
        # So just return
        return
    elif isinstance(received, CreateChatSessionID):
        # Don't worry about same session ids
        return
    else:
        raise NotImplementedError("Not implemented")


def _are_search_docs_equal(
    received: list[SearchDoc],
    expected: list[SearchDoc],
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    if len(received) != len(expected):
        return False

    received.sort(key=lambda x: x.document_id)
    expected.sort(key=lambda x: x.document_id)

    for received_document, expected_document in zip(received, expected):
        if received_document.document_id != expected_document.document_id:
            return False
        if received_document.link != expected_document.link:
            return False
        if received_document.blurb != expected_document.blurb:
            return False
        if received_document.source_type != expected_document.source_type:
            return False
        if received_document.hidden != expected_document.hidden:
            return False
    return True


def is_search_tool_document_delta_equal(
    received: SearchToolDocumentsDelta,
    expected: SearchToolDocumentsDelta,
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    received_documents = received.documents
    expected_documents = expected.documents

    return _are_search_docs_equal(received_documents, expected_documents)


def is_open_url_documents_equal(
    received: OpenUrlDocuments,
    expected: OpenUrlDocuments,
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    received_documents = received.documents
    expected_documents = expected.documents

    return _are_search_docs_equal(received_documents, expected_documents)


def is_agent_response_start_equal(
    received: AgentResponseStart,
    expected: AgentResponseStart,
) -> bool:
    """
    What we care about:
     - All documents are present (order does not)
     - Expected document_id, link, blurb, source_type and hidden
    """
    received_documents = received.final_documents
    expected_documents = expected.final_documents

    if received_documents is None and expected_documents is None:
        return True
    if not received_documents or not expected_documents:
        return False

    return _are_search_docs_equal(received_documents, expected_documents)


def is_image_generation_final_equal(
    received: ImageGenerationFinal,
    expected: ImageGenerationFinal,
) -> bool:
    """
    What we care about:
     - Number of images are the same
     - On each image, url and file_id are aligned such that url=/api/chat/file/{file_id}
     - Revised prompt is expected
     - Shape is expected
    """
    if len(received.images) != len(expected.images):
        return False

    for received_image, expected_image in zip(received.images, expected.images):
        if received_image.url != f"/api/chat/file/{received_image.file_id}":
            return False
        if received_image.revised_prompt != expected_image.revised_prompt:
            return False
        if received_image.shape != expected_image.shape:
            return False
    return True
