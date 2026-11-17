"""Chat's v2 wire: the v1 packet stream as ACP updates.

A client that sends ``protocol_version=2`` gets each streamed object as an
ACP-shaped update instead of a v1 packet, the shape Craft already sends (see
``server/features/build/sandbox/opencode/serve_client.py``):

- Answer text is an ``agent_message_chunk``; reasoning is an
  ``agent_thought_chunk``.
- A tool's start packet opens a ``tool_call``; every later packet at the same
  placement is a ``tool_call_update`` carrying that packet in
  ``_meta.onyx.packet``, and its ``section_end`` closes the call (``failed``
  after an ``error``). No v1 data is dropped, so a client can render tool
  bodies from the packets while typed payloads replace them tool by tool.
- Anything else (session ids, citations, stop, errors outside a call) is an
  ``_onyx/<type>`` extension notification with the v1 object as ``params``.

Every update carries ``_meta.onyx.version = 2``. v1 stays the default and is
unchanged; this only re-shapes what the chat pipeline already yields.
"""

from collections.abc import Iterator
from typing import Any

ONYX_CHAT_WIRE_VERSION = 2

# A tool's start packet: its ACP kind and title.
_TOOL_STARTS: dict[str, tuple[str, str]] = {
    "search_tool_start": ("search", "Searching"),
    "open_url_start": ("fetch", "Reading"),
    "image_generation_start": ("other", "Generating images"),
    "python_tool_start": ("execute", "Running Python"),
    "tool_call_argument_delta": ("execute", "Writing code"),
    "custom_tool_start": ("other", "Running tool"),
    "file_reader_start": ("read", "Reading file"),
    "memory_tool_start": ("edit", "Updating memory"),
    "memory_tool_no_access": ("edit", "Memory"),
    "deep_research_plan_start": ("think", "Generating plan"),
    "research_agent_start": ("other", "Researching"),
    "coding_agent_start": ("other", "Coding"),
    "bash_tool_start": ("execute", "Running command"),
    "code_mode_start": ("execute", "Running code"),
    "exec_command_start": ("execute", "Running command"),
    "write_stdin_start": ("execute", "Sending input"),
    "apply_patch_start": ("edit", "Editing files"),
}

_MESSAGE_TYPES = {"message_start", "message_delta"}
_REASONING_TYPES = {"reasoning_start", "reasoning_delta", "reasoning_done"}


def _onyx_meta(**fields: Any) -> dict[str, Any]:
    return {"onyx": {"version": ONYX_CHAT_WIRE_VERSION, **fields}}


def _call_id(placement: dict[str, Any]) -> str:
    """The id the frontend's chat adapter uses: ``tc:<turn>-<tab>[/<sub>]``."""
    call_id = f"tc:{placement.get('turn_index', 0)}-{placement.get('tab_index', 0)}"
    sub = placement.get("sub_turn_index")
    return f"{call_id}/{sub}" if sub is not None else call_id


class ChatAcpTranslator:
    """Turns chat's streamed objects (already dumped to dicts) into ACP
    updates. Holds the open tool calls, keyed by their placement."""

    def __init__(self) -> None:
        # Open tool calls: id -> whether an error arrived for it.
        self._open: dict[str, bool] = {}

    def translate(self, obj: dict[str, Any]) -> Iterator[dict[str, Any]]:
        packet = obj.get("obj")
        placement = obj.get("placement")
        if not isinstance(packet, dict) or not isinstance(placement, dict):
            # Not a packet: a session id, a message id, a stream error.
            yield self._notice(obj)
            return

        packet_type = packet.get("type")
        if not isinstance(packet_type, str):
            yield self._notice(obj)
            return

        if packet_type in _MESSAGE_TYPES or packet_type in _REASONING_TYPES:
            yield from self._text(packet_type, packet, placement)
            return

        call_id = _call_id(placement)
        if call_id not in self._open and packet_type in _TOOL_STARTS:
            kind, title = _TOOL_STARTS[packet_type]
            self._open[call_id] = False
            yield {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "kind": kind,
                "title": title,
                "status": "in_progress",
                "_meta": _onyx_meta(packet=packet, placement=placement),
            }
            return

        if call_id in self._open:
            if packet_type == "error":
                self._open[call_id] = True
            update: dict[str, Any] = {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "_meta": _onyx_meta(packet=packet, placement=placement),
            }
            if packet_type == "section_end":
                failed = self._open.pop(call_id)
                update["status"] = "failed" if failed else "completed"
            yield update
            return

        # A packet outside any tool call (stop, a top-level error, citations).
        yield self._notice(obj, packet_type)

    def _text(
        self, packet_type: str, packet: dict[str, Any], placement: dict[str, Any]
    ) -> Iterator[dict[str, Any]]:
        text = packet.get("content") if packet_type in _MESSAGE_TYPES else None
        if packet_type in _REASONING_TYPES:
            text = packet.get("reasoning")
        if not isinstance(text, str) or not text:
            return
        yield {
            "sessionUpdate": (
                "agent_message_chunk"
                if packet_type in _MESSAGE_TYPES
                else "agent_thought_chunk"
            ),
            "content": {"type": "text", "text": text},
            "_meta": _onyx_meta(placement=placement),
        }

    @staticmethod
    def _notice(obj: dict[str, Any], packet_type: str | None = None) -> dict[str, Any]:
        name = packet_type or obj.get("type") or "info"
        return {
            "method": f"_onyx/{name}",
            "params": obj,
            "_meta": _onyx_meta(),
        }
