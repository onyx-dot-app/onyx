"""Streaming projection survives callback boundaries without duplicate UI output."""

from io import BytesIO
from queue import Queue
from unittest.mock import MagicMock, patch

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatLoadedFile, ChatMessageSimple, LlmStepResult
from onyx.chat.pi.host_state import (
    ChatFileSnapshot,
    ChatMessageSnapshot,
    ChatStateSnapshot,
    CitationSnapshot,
    PresentationSnapshot,
)
from onyx.chat.pi.presentation import ChatPresentation
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import ChatFileType
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    FunctionCall,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)


def test_stream_projection_survives_every_callback_boundary() -> None:
    document = SearchDoc(
        document_id="doc",
        chunk_ind=0,
        semantic_identifier="Document",
        blurb="Text",
        source_type=DocumentSource.FILE,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
        link="https://example.com/doc",
    )
    chunks = [
        ModelResponseStream(id="step", created="0", choice=StreamingChoice(delta=delta))
        for delta in [
            Delta(reasoning_content="Thinking"),
            Delta(content="The answer ["),
            Delta(content="1] is here. ```"),
            Delta(content="\n[1]\n```"),
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="call",
                        function=FunctionCall(
                            name=PythonTool.NAME, arguments='{"code":"pri'
                        ),
                    )
                ]
            ),
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        function=FunctionCall(arguments='nt(\\"hello\\")"}')
                    )
                ]
            ),
        ]
    ]
    chunks.append(
        ModelResponseStream(
            id="step",
            created="0",
            choice=StreamingChoice(
                finish_reason="tool_calls",
                delta=Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id="call",
                            function=FunctionCall(
                                name=PythonTool.NAME,
                                arguments='{"code":"print(\\"hello\\")"}',
                            ),
                        )
                    ]
                ),
            ),
        )
    )

    def project(
        restore_between_chunks: bool,
    ) -> tuple[list[Packet | Exception | object], LlmStepResult, ChatStateSnapshot]:
        queue: Queue[tuple[int, Packet | Exception | object]] = Queue()
        emitter = Emitter(queue)
        state = ChatStateContainer()
        state.add_search_docs([document])
        citations = DynamicCitationProcessor()
        citations.update_citation_mapping({1: document})
        presenter = ChatPresentation(emitter, state, citations, 0, [document], 1.0)
        for chunk in chunks:
            presenter.feed(chunk)
            if restore_between_chunks:
                saved_state = ChatStateSnapshot.model_validate_json(
                    ChatStateSnapshot.capture(state).model_dump_json()
                )
                saved_citations = CitationSnapshot.model_validate_json(
                    CitationSnapshot.capture(citations).model_dump_json()
                )
                saved_presenter = PresentationSnapshot.model_validate_json(
                    presenter.snapshot().model_dump_json()
                )
                state = ChatStateContainer()
                saved_state.restore(state)
                citations = saved_citations.restore()
                presenter = ChatPresentation.restore(
                    saved_presenter, emitter, state, citations
                )
        result = presenter.finish()
        packets = []
        while not queue.empty():
            packets.append(queue.get_nowait()[1])
        return packets, result, ChatStateSnapshot.capture(state)

    uninterrupted = project(False)
    restored = project(True)
    assert restored == uninterrupted
    assert restored[1].tool_calls is not None
    assert restored[1].tool_calls[0].tool_args == {"code": 'print("hello")'}
    assert restored[2].emitted_citations == {1}
    assert "[[1]](https://example.com/doc)" in (restored[1].answer or "")


def test_binary_chat_files_round_trip_without_utf8_assumption() -> None:
    file = ChatFile(filename="image.png", content=b"\x89PNG\x00\xff")
    restored = ChatFileSnapshot.model_validate_json(
        ChatFileSnapshot.capture(file).model_dump_json()
    ).restore()
    assert restored == file


def test_lazy_history_images_survive_json_serialization() -> None:
    file = ChatLoadedFile.lazy_loaded(
        file_id="image",
        file_type=ChatFileType.IMAGE,
        filename="image.png",
        content_text=None,
        token_count=100,
        loader=lambda: b"\x89PNG\x00\xff",
    )
    message = ChatMessageSimple(
        message="Describe this",
        token_count=110,
        message_type=MessageType.USER,
        image_files=[file],
    )
    restored = ChatMessageSnapshot.model_validate_json(
        ChatMessageSnapshot.capture(message).model_dump_json()
    ).restore()
    assert restored.image_files is not None
    assert restored.image_files[0].content == b"\x89PNG\x00\xff"
    assert restored.model_dump() == message.model_dump()


def test_stored_tool_files_remain_lazy_across_callbacks() -> None:
    original_loader = MagicMock(
        side_effect=AssertionError("Admission must not download large tool files")
    )
    file = ChatFile.lazy_from_filename(
        filename="large.csv", source_file_id="stored-file", loader=original_loader
    )
    snapshot = ChatFileSnapshot.model_validate_json(
        ChatFileSnapshot.capture(file).model_dump_json()
    )
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
    try:
        restored = snapshot.restore()
        assert ChatFileSnapshot.capture(restored) == snapshot
        original_loader.assert_not_called()
        assert "source_file_id" not in restored.model_dump()
        CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")

        def read_file(file_id: str, mode: str) -> BytesIO:
            assert get_current_tenant_id() == "tenant_a"
            assert (file_id, mode) == ("stored-file", "b")
            return BytesIO(b"a,b\n1,2")

        with patch("onyx.chat.pi.host_state.get_default_file_store") as store:
            store.return_value.read_file.side_effect = read_file
            store.assert_not_called()
            assert restored.content == b"a,b\n1,2"
            assert restored.content == b"a,b\n1,2"
            store.return_value.read_file.assert_called_once_with(
                "stored-file", mode="b"
            )
        assert get_current_tenant_id() == "tenant_b"
        original_loader.assert_not_called()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
