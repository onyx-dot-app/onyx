"""Code mode runs programs that call an MCP tool, through the chat flow and the DB."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextvars import copy_context
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent
from pydantic import BaseModel, JsonValue
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import get_processing_stream_id
from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.chat.incognito_context import teardown_incognito_session
from onyx.chat.stop_signal_checker import request_stop
from onyx.db.enums import (
    IncognitoRecordMode,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import Persona, Tool, ToolCall, User
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.server.query_and_chat.chat_backend import get_chat_session
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    CodeModeDelta,
    CodeModeStart,
    CustomToolDelta,
    CustomToolStart,
    ImageGenerationFinal,
    OverallStop,
    Packet,
    SectionEnd,
)
from onyx.tools.tool_implementations.code_mode.models import CodeModeExecutionResult
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_name import normalize_external_tool_name
from tests.external_dependency_unit.answer.stream_test_utils import final_answer
from tests.external_dependency_unit.code_mode_helpers import (
    ChatLLM,
    assert_cells_released,
    code_mode_shape,
    code_step,
    final_deltas,
    last_tool_text,
    saved_cells,
    send,
    tool_step,
    wait_step,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.mock_image_provider import (
    use_mock_image_generation_provider,
)

PRINTED = "Hello, alpha! | Hello, beta!"


DENIED = "403 Forbidden: repo access denied"


class Forecast(BaseModel):
    """The structured result of the test server's `forecast` tool."""

    city: str
    high: int


class ServerSignals:
    """What the test MCP server's tools report to one test."""

    def __init__(self) -> None:
        # Set when `slow` starts; `slow_release` lets its calls return.
        self.slow_started = threading.Event()
        self.slow_release = threading.Event()


_signals = ServerSignals()


@pytest.fixture(autouse=True)
def signals() -> Generator[ServerSignals, None, None]:
    """Fresh signals for each test; calls left running return at its end."""
    global _signals
    current = ServerSignals()
    _signals = current
    yield current
    current.slow_release.set()


@pytest.fixture(scope="module")
def mcp_server_url() -> Generator[str, None, None]:
    """A FastMCP server with `hello`, `slow`, `chart`, `forecast` and `deny` tools,
    served in this process."""
    mcp = FastMCP("Code mode test server")

    @mcp.tool
    def hello(name: str) -> str:
        """Say hi."""
        return f"Hello, {name}!"

    @mcp.tool
    async def slow(name: str) -> str:
        """Say hi once the test releases the call."""
        current = _signals
        current.slow_started.set()
        for _ in range(600):
            if current.slow_release.is_set():
                break
            await asyncio.sleep(0.05)
        return f"Slowly, {name}!"

    @mcp.tool
    def chart(name: str) -> list[TextContent | ImageContent]:
        """Return a caption with an image."""
        return [
            TextContent(type="text", text=f"Chart for {name}"),
            ImageContent(type="image", mimeType="image/png", data="aGVsbG8="),
        ]

    @mcp.tool
    def forecast(name: str) -> Forecast:
        """Return a structured forecast."""
        return Forecast(city=name, high=21)

    @mcp.tool
    def deny(name: str) -> str:
        """Fail as a server that refuses the request."""
        raise ToolError(f"{DENIED} for {name}")

    # The server takes the bound socket, so no other process can take the port.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            mcp.http_app(path="/mcp"), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(
        target=lambda: asyncio.run(server.serve(sockets=[sock])), daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("MCP test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)
    sock.close()


# Code mode includes the server ID in each MCP function namespace.
MCP_SERVER = "acme"


def _persona_with_mcp_tool(
    db_session: Session,
    user: User,
    server_url: str,
    tool_names: Sequence[str] = ("hello",),
    output_schema: dict[str, JsonValue] | None = None,
) -> tuple[Persona, str]:
    mcp_server = create_mcp_server__no_commit(
        owner_email=user.email,
        name=MCP_SERVER,
        description="In-process MCP server",
        server_url=server_url,
        auth_type=MCPAuthenticationType.NONE,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        db_session=db_session,
    )
    db_session.flush()
    tools = [
        Tool(
            name=name,
            display_name=name.title(),
            description="Say hi.",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            # FastMCP wraps a str result as {"result": str}.
            mcp_output_schema=output_schema
            or {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
            user_id=user.id,
        )
        for name in tool_names
    ]
    persona = Persona(
        name=f"Code Mode Persona {uuid4().hex[:8]}",
        description="Persona with one MCP tool",
        system_prompt="You are a helpful assistant",
        task_prompt="",
        tools=tools,
        document_sets=[],
        user_id=user.id,
        groups=[],
        is_listed=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
    )
    db_session.add_all([*tools, persona])
    db_session.commit()
    db_session.refresh(persona)
    return persona, f"mcp__{mcp_server.id}__{MCP_SERVER}"


def _code_mode_packets(packets: Sequence[object]) -> list[Packet]:
    return [
        packet
        for packet in packets
        if isinstance(packet, Packet)
        and isinstance(
            packet.obj,
            (CodeModeStart, CodeModeDelta, CustomToolStart, CustomToolDelta),
        )
    ]


def _assert_code_mode_block(packets: Sequence[object], program: str) -> None:
    block = _code_mode_packets(packets)
    starts = [p for p in block if isinstance(p.obj, CodeModeStart)]
    assert len(starts) == 1
    start = starts[0]
    assert isinstance(start.obj, CodeModeStart)
    assert start.obj.code == program
    assert start.placement.sub_turn_index is None

    nested = [p for p in block if isinstance(p.obj, (CustomToolStart, CustomToolDelta))]
    assert {p.placement.sub_turn_index for p in nested} == {0, 1}
    for packet in nested:
        assert packet.placement.turn_index == start.placement.turn_index
        assert packet.placement.tab_index == start.placement.tab_index
    nested_data = sorted(
        json.dumps(p.obj.data) for p in nested if isinstance(p.obj, CustomToolDelta)
    )
    assert len(nested_data) == 2
    assert "Hello, alpha!" in nested_data[0]
    assert "Hello, beta!" in nested_data[1]

    deltas = [p.obj for p in block if isinstance(p.obj, CodeModeDelta)]
    final = [delta for delta in deltas if delta.status is not None]
    assert len(final) == 1
    assert final[0].status == "completed"
    assert final[0].tool_call_count == 2
    assert PRINTED in "".join(delta.stdout for delta in deltas)

    # The code mode block closes at the parent placement.
    assert any(
        isinstance(p, Packet)
        and isinstance(p.obj, SectionEnd)
        and p.placement == start.placement
        for p in packets
    )


def _press_stop(chat_session_id: UUID) -> None:
    cache = get_cache_backend()
    stream_id = get_processing_stream_id(chat_session_id, cache)
    assert stream_id is not None
    request_stop(chat_session_id, cache, stream_id=stream_id)


def _stop_on_stdout(chat_session_id: UUID, text: str) -> Callable[[object], None]:
    """Press Stop once a live code mode block prints `text`."""
    pressed = False

    def on_part(part: object) -> None:
        nonlocal pressed
        if (
            not pressed
            and isinstance(part, Packet)
            and isinstance(part.obj, CodeModeDelta)
            and text in part.obj.stdout
        ):
            pressed = True
            _press_stop(chat_session_id)

    return on_part


def test_code_mode_program_calls_mcp_tool_in_parallel(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_user")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    program = (
        "import asyncio\n"
        f"a, b = await asyncio.gather({namespace}__hello(name='alpha'), {namespace}__hello(name='beta'))\n"
        "print(a['result'] + ' | ' + b['result'])\n"
    )
    llm = ChatLLM([code_step("code", program), Delta(content="Both greetings worked.")])
    parts = send(chat_session.id, user, llm, "Greet alpha and beta.")

    assert final_answer(parts) == "Both greetings worked."
    _assert_code_mode_block(parts, program)

    # The second model step receives the program output as the tool result.
    assert len(llm.requests) == 2
    assert PRINTED in last_tool_text(llm, "code")

    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    assert len(chat_detail.packets) == 1
    _assert_code_mode_block(chat_detail.packets[0], program)


def _tool_labels(packets: Sequence[object]) -> list[tuple[str, str]]:
    return [
        (packet.obj.tool_name, packet.obj.display_name)
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, CustomToolStart)
    ]


def test_saved_mcp_calls_replay_the_tool_display_name(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("tool_label_user")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    tool_name = normalize_external_tool_name(f"{namespace}__hello")
    llm = ChatLLM(
        [tool_step(tool_name, "call", {"name": "alpha"}), Delta(content="Done.")]
    )
    parts = send(chat_session.id, user, llm, "Greet alpha.", code_mode=False)

    assert final_answer(parts) == "Done."
    assert _tool_labels(parts) == [(tool_name, "hello")]
    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    assert len(chat_detail.packets) == 1
    assert _tool_labels(chat_detail.packets[0]) == [(tool_name, "hello")]


@pytest.mark.parametrize("temporary", [False, True])
def test_stored_values_reach_a_program_in_a_later_turn(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
    temporary: bool,
) -> None:
    user = make_test_user(f"code_mode_store_user_{temporary}")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    if temporary:
        # A temporary chat keeps its history, and so the store, in Redis.
        chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
        db_session.commit()

    try:
        first = ChatLLM(
            [
                code_step(
                    "store",
                    f"greeting = await {namespace}__hello(name='alpha')\n"
                    "store('greeting', {'text': greeting['result']})\n"
                    "store('unused', None)\n"
                    "raise ValueError('after storing')\n",
                ),
                Delta(content="Saved."),
            ]
        )
        assert final_answer(send(chat_session.id, user, first, "Save a greeting.")) == (
            "Saved."
        )
        # A program that stops at an uncaught exception still commits its writes.
        # Deleting a missing key changes nothing, so the commit leaves it out.
        stored = last_tool_text(first, "store")
        assert "ValueError: after storing" in stored
        assert stored.endswith("Stored: greeting.")

        # A new turn runs in a new interpreter; the store comes from the saved turn.
        second = ChatLLM(
            [
                code_step(
                    "load",
                    "print(load('greeting')['text'])\n"
                    "try:\n"
                    "    greeting\n"
                    "except NameError:\n"
                    "    print('fresh interpreter')\n",
                ),
                Delta(content="Loaded."),
            ]
        )
        assert final_answer(send(chat_session.id, user, second, "Read it back.")) == (
            "Loaded."
        )
        text = last_tool_text(second, "load")
        assert "Hello, alpha!\nfresh interpreter" in text
    finally:
        if temporary:
            teardown_incognito_session(chat_session.id)


def _nested_hello_data(packets: Sequence[object]) -> list[str]:
    return [
        json.dumps(packet.obj.data)
        for packet in packets
        if isinstance(packet, Packet)
        and isinstance(packet.obj, CustomToolDelta)
        and packet.placement.sub_turn_index == 0
    ]


def test_stop_keeps_the_calls_a_program_made(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
    signals: ServerSignals,
) -> None:
    user = make_test_user("code_mode_stop_user")
    persona, namespace = _persona_with_mcp_tool(
        db_session, user, mcp_server_url, tool_names=("hello", "slow")
    )
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    llm = ChatLLM(
        [
            code_step(
                "code",
                f"a = await {namespace}__hello(name='alpha')\nb = await {namespace}__slow(name='beta')\nprint(b)\n",
            )
        ]
    )

    def stop_when_slow_starts() -> None:
        # The user presses Stop while the program waits on its second call.
        assert signals.slow_started.wait(30)
        _press_stop(chat_session.id)

    stopper = threading.Thread(target=copy_context().run, args=(stop_when_slow_starts,))
    stopper.start()
    try:
        parts = send(chat_session.id, user, llm, "Greet alpha, then beta.")
    finally:
        signals.slow_release.set()
        stopper.join(timeout=30)

    stops = [
        part.obj
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, OverallStop)
    ]
    assert [stop.stop_reason for stop in stops] == ["user_cancelled"]
    # The live stream ends at Stop; the client marks the open step as cancelled.
    assert any("Hello, alpha!" in data for data in _nested_hello_data(parts))
    assert not any(
        isinstance(part, Packet)
        and isinstance(part.obj, CodeModeDelta)
        and part.obj.status is not None
        for part in parts
    )

    # A reload shows the same cancelled step with the call that ran.
    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    [final] = final_deltas(replayed)
    assert (final.status, final.tool_call_count) == ("cancelled", 2)
    assert any("Hello, alpha!" in data for data in _nested_hello_data(replayed))

    # The next turn's model learns which calls ran.
    follow_up = ChatLLM([Delta(content="Alpha was greeted.")])
    assert final_answer(send(chat_session.id, user, follow_up, "What ran?")) == (
        "Alpha was greeted."
    )
    text = last_tool_text(follow_up, "code")
    assert f"[0] {namespace}__hello: ok\n[1] {namespace}__slow: unfinished" in text
    assert "may have had effects" in text


def test_stop_during_computation_saves_the_cancelled_program(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_busy_stop_user")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    llm = ChatLLM(
        [
            code_step(
                "busy",
                f"await {namespace}__hello(name='alpha')\nprint('looping')\nwhile True:\n    pass\n",
            )
        ]
    )
    started = time.monotonic()
    # The live output shows the program in its busy loop on a sandbox worker.
    parts = send(
        chat_session.id,
        user,
        llm,
        "Greet alpha, then loop.",
        on_part=_stop_on_stdout(chat_session.id, "looping"),
    )
    # Far less than the program's compute limit.
    assert time.monotonic() - started < 20
    assert [
        part.obj.stop_reason
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, OverallStop)
    ] == ["user_cancelled"]

    [saved] = (
        db_session.query(ToolCall)
        .filter(ToolCall.chat_session_id == chat_session.id)
        .all()
    )
    assert saved.result is not None
    details = saved.result.details
    assert isinstance(details, CodeModeExecutionResult)
    assert details.status == "cancelled"
    assert [(call.function_name, call.state) for call in details.calls] == [
        (f"{namespace}__hello", "ok")
    ]

    # A reload shows the cancelled step.
    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    assert final_deltas(replayed)[0].status == "cancelled"

    # The sandbox replaced the killed worker: the next program runs.
    follow_up = ChatLLM([code_step("next", "print(6 * 7)\n"), Delta(content="42.")])
    assert final_answer(send(chat_session.id, user, follow_up, "Compute.")) == "42."
    assert "Output:\n42" in last_tool_text(follow_up, "next")


IMAGE_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAIAAACRXR/mAAAAVElEQVR42u3WwQkAIAwDQOP+O9cN+lJUu"
    "HylcFApyWhTVc1rkkOzczwZLCwsrN9YuXXH+1lLxMLCwtpz5XV5fwsLC0uX1+WxsLCwdHldHgsLC+ux"
    "LK9hJFqMAN43AAAAAElFTkSuQmCC"
)


def _image_final_placements(packets: Sequence[object]) -> list[int | None]:
    return [
        packet.placement.sub_turn_index
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, ImageGenerationFinal)
    ]


@pytest.mark.usefixtures("full_deployment_setup")
def test_a_program_generates_an_image(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("code_mode_image_user")
    image_tool = (
        db_session.query(Tool)
        .filter(Tool.in_code_tool_id == ImageGenerationTool.__name__)
        .one()
    )
    persona = Persona(
        name=f"Code Mode Image Persona {uuid4().hex[:8]}",
        description="Persona with image generation",
        system_prompt="You are a helpful assistant",
        task_prompt="",
        tools=[image_tool],
        document_sets=[],
        user_id=user.id,
        groups=[],
        is_listed=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    llm = ChatLLM(
        [
            code_step(
                "draw",
                "images = await generate_image(prompt='A dog on a rocketship')\n"
                "print(images[0]['file_id'])\n",
            ),
            Delta(content="Here is the dog."),
        ]
    )
    file_store = MagicMock()
    file_store.save_file.return_value = "123"
    with (
        use_mock_image_generation_provider() as provider,
        patch("onyx.file_store.utils.get_default_file_store", return_value=file_store),
    ):
        provider.add_image(IMAGE_PNG)
        parts = send(chat_session.id, user, llm, "Draw a dog on a rocketship.")

    assert final_answer(parts) == "Here is the dog."
    assert _image_final_placements(parts) == [0]
    assert "Output:\n123" in last_tool_text(llm, "draw")

    [saved] = (
        db_session.query(ToolCall)
        .filter(ToolCall.chat_session_id == chat_session.id)
        .all()
    )
    assert saved.result is not None
    details = saved.result.details
    assert isinstance(details, CodeModeExecutionResult)
    image = details.calls[0].details
    assert isinstance(image, FinalImageGenerationResponse)
    assert [generated.file_id for generated in image.generated_images] == ["123"]

    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    assert _image_final_placements(replayed) == [0]


def test_wait_code_collects_the_result_of_a_yielded_cell(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_cell_user")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    llm = ChatLLM(
        [
            code_step(
                "start",
                "print('started')\nyield_control()\n"
                f"greeting = await {namespace}__hello(name='alpha')\nprint(greeting['result'])\n"
                "store('greeting', greeting)\n",
            ),
            wait_step("wait", 1),
            Delta(content="Done."),
        ]
    )
    parts = send(chat_session.id, user, llm, "Greet alpha in the background.")

    assert final_answer(parts) == "Done."
    started = last_tool_text(llm, "start")
    assert started.startswith("Execution running in cell 1 after ")
    assert "Output:\nstarted" in started
    waited = last_tool_text(llm, "wait")
    assert waited.startswith("Execution completed in cell 1 in ")
    assert "Output:\nHello, alpha!" in waited
    assert "Stored: greeting." in waited

    saved = saved_cells(db_session, chat_session.id)
    assert [(d.cell_id, d.observation, d.status) for d in saved] == [
        (1, 0, "running"),
        (1, 1, "completed"),
    ]
    assert [(call.function_name, call.state) for call in saved[1].calls] == [
        (f"{namespace}__hello", "ok")
    ]

    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    starts = [
        packet.obj
        for packet in replayed
        if isinstance(packet, Packet) and isinstance(packet.obj, CodeModeStart)
    ]
    assert [(start.cell_id, start.observation) for start in starts] == [
        (None, 0),
        (1, 1),
    ]
    assert [delta.status for delta in final_deltas(replayed)] == [
        "running",
        "completed",
    ]

    follow_up = ChatLLM(
        [
            code_step("load", "print(load('greeting')['result'])\n"),
            Delta(content="Read."),
        ]
    )
    assert final_answer(send(chat_session.id, user, follow_up, "Read it.")) == ("Read.")
    loaded = last_tool_text(follow_up, "load")
    assert "Output:\nHello, alpha!" in loaded
    # Ids continue after the highest id of the branch.
    assert "in cell 2" in loaded


def test_a_cell_running_at_the_answer_gets_a_closing_record(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
    signals: ServerSignals,
) -> None:
    user = make_test_user("code_mode_closing_user")
    persona, namespace = _persona_with_mcp_tool(
        db_session, user, mcp_server_url, tool_names=("hello", "slow")
    )
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )

    def after_print() -> None:
        # `slow` starts after the greeting printed and runs past the answer.
        assert signals.slow_started.wait(30)

    llm = ChatLLM(
        [
            code_step(
                "start",
                "yield_control()\n"
                f"greeting = await {namespace}__hello(name='alpha')\nprint(greeting['result'])\n"
                f"await {namespace}__slow(name='beta')\n",
            ),
            Delta(content="Answered early."),
        ],
        gates={1: after_print},
    )
    started = time.monotonic()
    parts = send(chat_session.id, user, llm, "Start, then answer.")
    assert time.monotonic() - started < 20
    assert final_answer(parts) == "Answered early."
    assert_cells_released()

    live_closing = [delta for delta in final_deltas(parts) if delta.response_ended]
    assert [delta.status for delta in live_closing] == ["terminated"]

    [saved] = saved_cells(db_session, chat_session.id)
    assert saved.status == "running"
    assert saved.closing is not None
    assert (saved.closing.reason, saved.closing.status) == (
        "response_ended",
        "terminated",
    )
    assert [(call.function_name, call.state) for call in saved.closing.calls] == [
        (f"{namespace}__hello", "ok"),
        (f"{namespace}__slow", "unfinished"),
    ]
    assert saved.closing.stdout == "Hello, alpha!\n"

    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    replayed_closing = [
        delta for delta in final_deltas(replayed) if delta.response_ended
    ]
    assert [delta.status for delta in replayed_closing] == ["terminated"]
    assert code_mode_shape(replayed) == code_mode_shape(parts)

    follow_up = ChatLLM([Delta(content="It greeted alpha.")])
    assert final_answer(send(chat_session.id, user, follow_up, "What ran?")) == (
        "It greeted alpha."
    )
    text = last_tool_text(follow_up, "start")
    assert text.endswith(
        "Cell 1 stopped when the response ended.\n\nOutput:\nHello, alpha!\n\n"
        f"Tool calls:\n[0] {namespace}__hello: ok\n[1] {namespace}__slow: unfinished\n"
        "All of these calls may have had effects, also unfinished calls. Check "
        "before you retry."
    )


def test_stop_during_wait_code_stops_the_cell(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_cell_stop_user")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    llm = ChatLLM(
        [
            code_step(
                "start",
                f"import asyncio\nawait {namespace}__hello(name='alpha')\nprint('a')\n"
                "yield_control()\nprint('b')\nawait asyncio.sleep(60)\n",
            ),
            wait_step("wait", 1),
        ]
    )
    started = time.monotonic()
    # wait_code streams the output printed since the last observation.
    parts = send(
        chat_session.id,
        user,
        llm,
        "Start and wait.",
        on_part=_stop_on_stdout(chat_session.id, "b"),
    )
    assert time.monotonic() - started < 20
    assert [
        part.obj.stop_reason
        for part in parts
        if isinstance(part, Packet) and isinstance(part.obj, OverallStop)
    ] == ["user_cancelled"]
    assert_cells_released()

    saved = saved_cells(db_session, chat_session.id)
    assert [(d.observation, d.status, d.stdout) for d in saved] == [
        (0, "running", "a\n"),
        (1, "cancelled", "b\n"),
    ]
    # The last observation reports the end, so no closing record is added.
    assert saved[0].closing is None
    waited = (
        db_session.query(ToolCall)
        .filter(ToolCall.chat_session_id == chat_session.id)
        .order_by(ToolCall.id.desc())
        .first()
    )
    assert waited is not None and waited.result is not None
    assert waited.result.is_error
    assert waited.result.text.startswith("Execution was cancelled in cell 1 after ")

    # A later turn reads the end of the cell with the calls of all its observations.
    follow_up = ChatLLM([Delta(content="It was stopped.")])
    assert final_answer(send(chat_session.id, user, follow_up, "What ran?")) == (
        "It was stopped."
    )
    assert "Tool calls:" not in last_tool_text(follow_up, "start")
    ended = last_tool_text(follow_up, "wait")
    assert f"Tool calls:\n[0] {namespace}__hello: ok\n" in ended


def test_an_unobserved_commit_after_a_later_one_keeps_the_live_store(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
    signals: ServerSignals,
) -> None:
    user = make_test_user("code_mode_commit_order_user")
    persona, namespace = _persona_with_mcp_tool(
        db_session, user, mcp_server_url, tool_names=("hello", "slow")
    )
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )

    # Threads that earlier tests left; this response waits only for its own.
    earlier_threads = set(threading.enumerate())

    def after_cell_1_completes() -> None:
        # Cell 2 committed `k` in step 1; cell 1 commits it after, unobserved.
        signals.slow_release.set()
        deadline = time.monotonic() + 30
        while any(
            thread.name.startswith("code-mode-") and thread not in earlier_threads
            for thread in threading.enumerate()
        ):
            assert time.monotonic() < deadline
            time.sleep(0.05)

    llm = ChatLLM(
        [
            code_step(
                "first",
                f"yield_control()\nawait {namespace}__slow(name='a')\nstore('k', 'a')\n",
            ),
            code_step("second", "store('k', 'b')\n"),
            code_step("live", "print(load('k'))\n"),
            Delta(content="Done."),
        ],
        gates={2: after_cell_1_completes},
    )
    parts = send(chat_session.id, user, llm, "Store k twice.")
    assert final_answer(parts) == "Done."
    assert "Output:\na" in last_tool_text(llm, "live")

    first, second, _live = saved_cells(db_session, chat_session.id)
    assert first.closing is not None
    first_commit = first.closing.commit
    second_commit = second.commit
    assert first.closing.status == "completed"
    assert first_commit is not None and first_commit.writes == {"k": "a"}
    assert second_commit is not None and second_commit.writes == {"k": "b"}
    assert first_commit.ordinal > second_commit.ordinal

    chat_detail = get_chat_session(
        session_id=chat_session.id, user=user, db_session=db_session
    )
    [replayed] = chat_detail.packets
    assert [
        delta.status for delta in final_deltas(replayed) if delta.response_ended
    ] == ["completed"]

    follow_up = ChatLLM(
        [code_step("next", "print(load('k'))\n"), Delta(content="Read.")]
    )
    assert final_answer(send(chat_session.id, user, follow_up, "Read k.")) == "Read."
    assert "Output:\na" in last_tool_text(follow_up, "next")


def test_a_server_reported_tool_error_reaches_the_program_and_the_model(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_tool_error_user")
    persona, namespace = _persona_with_mcp_tool(
        db_session, user, mcp_server_url, tool_names=("deny", "hello")
    )
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    # A program can catch the error and sees the server's text.
    program = ChatLLM(
        [
            code_step(
                "code",
                "try:\n"
                f"    await {namespace}__deny(name='onyx')\n"
                "except Exception as error:\n"
                "    print('caught', error)\n",
            ),
            Delta(content="The server refused."),
        ]
    )
    assert final_answer(send(chat_session.id, user, program, "Read the repo.")) == (
        "The server refused."
    )
    assert f"Output:\ncaught {DENIED} for onyx" in last_tool_text(program, "code")

    # A direct call returns the same text as an error result. The refusal is the
    # tool's result, not a credentials failure. A direct call that succeeds reads
    # the server's text, not its structured content.
    direct = ChatLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="direct",
                        index=0,
                        function=ResponseFunctionCall(
                            name=f"{namespace}__deny",
                            arguments=json.dumps({"name": "onyx"}),
                        ),
                    ),
                    ChatCompletionDeltaToolCall(
                        id="greet",
                        index=1,
                        function=ResponseFunctionCall(
                            name=f"{namespace}__hello",
                            arguments=json.dumps({"name": "onyx"}),
                        ),
                    ),
                ]
            ),
            Delta(content="Refused again."),
        ]
    )
    assert final_answer(
        send(chat_session.id, user, direct, "Try directly.", code_mode=False)
    ) == ("Refused again.")
    assert json.loads(last_tool_text(direct, "direct")) == {
        "error": f"{DENIED} for onyx"
    }
    assert json.loads(last_tool_text(direct, "greet")) == {
        "tool_result": "Hello, onyx!"
    }

    rows = {
        row.tool_call_id: row
        for row in db_session.query(ToolCall).filter(
            ToolCall.chat_session_id == chat_session.id
        )
    }
    in_program, direct_call = rows["code"], rows["direct"]
    assert in_program.result is not None
    details = in_program.result.details
    assert isinstance(details, CodeModeExecutionResult)
    assert details.status == "completed"
    assert [(call.function_name, call.state) for call in details.calls] == [
        (f"{namespace}__deny", "error")
    ]
    assert direct_call.result is not None and direct_call.result.is_error


def test_mcp_media_results_reach_the_model_as_their_text(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_mcp_media_user")
    persona, namespace = _persona_with_mcp_tool(
        db_session, user, mcp_server_url, tool_names=("chart",)
    )
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    program = ChatLLM(
        [
            code_step("code", f"print(await {namespace}__chart(name='q2'))\n"),
            Delta(content="Charted."),
        ]
    )
    assert final_answer(send(chat_session.id, user, program, "Chart it.")) == (
        "Charted."
    )
    in_program = last_tool_text(program, "code")
    assert "Chart for q2" in in_program
    assert "omitted" not in in_program

    direct = ChatLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="direct",
                        index=0,
                        function=ResponseFunctionCall(
                            name=f"{namespace}__chart",
                            arguments=json.dumps({"name": "q3"}),
                        ),
                    )
                ]
            ),
            Delta(content="Charted again."),
        ]
    )
    assert final_answer(
        send(chat_session.id, user, direct, "Chart directly.", code_mode=False)
    ) == ("Charted again.")
    direct_text = last_tool_text(direct, "direct")
    assert "Chart for q3" in direct_text
    assert "omitted" not in direct_text


def test_a_program_finds_a_deferred_mcp_function_with_tool_search(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_tool_search_user")
    persona, namespace = _persona_with_mcp_tool(db_session, user, mcp_server_url)
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    llm = ChatLLM(
        [
            code_step(
                "find",
                "[match] = await tool_search('say hi', limit=1)\n"
                "print(match['name'])\n"
                "print(match['stub'])\n"
                f"greeting = await {namespace}__hello(name='alpha')\n"
                "print(greeting['result'])\n",
            ),
            Delta(content="Found it."),
        ]
    )
    assert final_answer(send(chat_session.id, user, llm, "Say hi.")) == "Found it."

    # MCP functions are deferred: the description names the server, not the stub.
    [description] = [
        tool["function"]["description"]
        for tool in llm.requests[0]["tools"]
        if tool["function"]["name"] == "execute_code"
    ]
    assert f"the MCP server `{namespace}`" in description
    assert f"{namespace}__hello" not in description

    text = last_tool_text(llm, "find")
    assert f"Output:\n{namespace}__hello\n" in text
    # The stub types the result from the server's output schema.
    assert f"-> Mcp{persona.tools[0].mcp_server_id}AcmeHelloResult" in text
    assert text.rstrip().endswith("Hello, alpha!")


def test_a_program_receives_the_structured_result_of_an_mcp_tool(
    db_session: Session,
    make_test_user: MakeTestUser,
    mcp_server_url: str,
) -> None:
    user = make_test_user("code_mode_mcp_structured_user")
    persona, namespace = _persona_with_mcp_tool(
        db_session,
        user,
        mcp_server_url,
        tool_names=("forecast",),
        output_schema=Forecast.model_json_schema(),
    )
    chat_session = create_chat_session_from_request(
        chat_session_request=ChatSessionCreationRequest(persona_id=persona.id),
        user=user,
        db_session=db_session,
    )
    program = (
        f"forecast = await {namespace}__forecast(name='Oslo')\n"
        "print(type(forecast).__name__, forecast['city'], forecast['high'] + 1)\n"
    )
    llm = ChatLLM([code_step("code", program), Delta(content="Forecasted.")])
    assert final_answer(send(chat_session.id, user, llm, "Forecast Oslo.")) == (
        "Forecasted."
    )
    assert "dict Oslo 22" in last_tool_text(llm, "code")
