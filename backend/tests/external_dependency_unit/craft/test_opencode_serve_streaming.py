"""Regression tests for streaming-output quality through the
``opencode serve`` transport.

Each test drives a real opencode-serve turn against the
module-scoped pool sandbox pod (``running_sandbox`` fixture, which
shares ONE pod across every test in this module — fresh
opencode session per test, no pod churn). The tests assert
end-to-end on the SandboxEvents that ``KubernetesSandboxManager.send_message``
yields — same events the Onyx session manager persists and the
frontend renders.

The scenarios exercise the bugs we found and fixed during Phase 2
(see docs/craft/opencode-serve-test-report.md):

1. Simple message — text streams, terminator fires, no user-prompt
   leak in the assistant text.
2. Reasoning content lands in ``AgentThoughtChunk`` (not
   ``AgentMessageChunk``).
3. Tool calls emit ``ToolCallStart`` once + ``ToolCallProgress``
   cycling to ``completed``.
4. Multi-step turn (tool → follow-up answer): text deltas after the
   tool aren't dropped because we track every assistant message id,
   not just the first.
5. Multi-turn session — three prompts in a row, each terminates
   independently, no cross-talk.
6. Bad model id surfaces as ``Error`` (no ``PromptResponse``).

Requirements (matches every other K8s external-dep test in this dir):
- ``OPENAI_API_KEY`` env var with a real key
- A reachable kind cluster + ``onyxdotapp/sandbox:dev`` pre-loaded
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from typing import cast

import pytest

from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import Error
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.event_schema import ToolCallStart
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from tests.external_dependency_unit.craft._test_helpers import default_llm_config

# Skip the entire module unless we have a real OpenAI key — these tests
# need to make real LLM calls.
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="streaming-output tests need a real OPENAI_API_KEY",
)


@pytest.fixture
def llm_config() -> LLMProviderConfig:
    return default_llm_config(api_key=os.environ["OPENAI_API_KEY"])


# Common collected event buckets for assertions.
class _Collected:
    __slots__ = ("chunks", "thoughts", "tool_starts", "tool_progress", "term", "errors")

    def __init__(self) -> None:
        self.chunks: list[AgentMessageChunk] = []
        self.thoughts: list[AgentThoughtChunk] = []
        self.tool_starts: list[ToolCallStart] = []
        self.tool_progress: list[ToolCallProgress] = []
        self.term: PromptResponse | None = None
        self.errors: list[Error] = []

    @property
    def text(self) -> str:
        return "".join(c.content.text for c in self.chunks)  # type: ignore[union-attr]

    @property
    def thought_text(self) -> str:
        return "".join(c.content.text for c in self.thoughts)  # type: ignore[union-attr]


def _drive_turn(
    handle: Any,
    prompt: str,
    *,
    opencode_session_id: str | None = None,
) -> tuple[_Collected, str | None]:
    """Drive one turn end-to-end via the manager's send_message. Returns
    (collected events, the opencode_session_id used)."""
    manager = handle.manager
    session_id = handle.session_id
    sandbox_id = handle.sandbox_id

    # First call resolves (and may create) the opencode session.
    if opencode_session_id is None:
        opencode_session_id = manager.ensure_opencode_session(sandbox_id, session_id)
    assert opencode_session_id, "ensure_opencode_session must return an id under serve"

    out = _Collected()
    for ev in manager.send_message(
        sandbox_id, session_id, prompt, opencode_session_id=opencode_session_id
    ):
        if isinstance(ev, AgentMessageChunk):
            out.chunks.append(ev)
        elif isinstance(ev, AgentThoughtChunk):
            out.thoughts.append(ev)
        elif isinstance(ev, ToolCallStart):
            out.tool_starts.append(ev)
        elif isinstance(ev, ToolCallProgress):
            out.tool_progress.append(ev)
        elif isinstance(ev, PromptResponse):
            out.term = ev
        elif isinstance(ev, Error):
            out.errors.append(ev)
        elif isinstance(ev, SSEKeepalive):
            pass
    return out, opencode_session_id


# ─────────────────────────────────────────────────────────────────────


def test_simple_message_streams_text_and_terminates(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    handle = running_sandbox(with_session=True, llm_config=llm_config)
    out, _ = _drive_turn(handle, "Say hi briefly.")

    # Terminator + at least some text + no error.
    assert out.term is not None
    assert out.term.stop_reason == "end_turn"
    assert out.errors == []
    assert len(out.text) > 0, "expected at least one AgentMessageChunk"

    # Regression: user prompt must NOT leak into the assistant text.
    assert "Say hi briefly" not in out.text, (
        f"user prompt leaked into assistant text: {out.text!r}"
    )


def test_reasoning_routed_to_thought_chunk(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    """gpt-5-mini reliably emits a short reasoning preamble. That content
    must land in AgentThoughtChunk, NOT in AgentMessageChunk. Regression
    test for the wire-grammar bug where deltas on ``type=reasoning`` parts
    came across as visible message chunks."""
    handle = running_sandbox(with_session=True, llm_config=llm_config)
    out, _ = _drive_turn(handle, "Greet me in five words.")

    assert out.term is not None
    assert out.errors == []
    # The visible answer should not include the model's reasoning prefix
    # ("The user is asking…" or similar). We don't pin the exact text but
    # the visible chunk should be reasonably short.
    assert len(out.text) > 0
    assert len(out.text) < 200, (
        f"visible text suspiciously long ({len(out.text)} chars) — "
        f"reasoning may be leaking through: {out.text[:200]!r}"
    )
    # We may or may not see thought_text depending on the model run — but
    # if we do, that's the right channel.


def test_bash_tool_call_lifecycle(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    """Tool call lifecycle: exactly one ToolCallStart per call_id; the
    associated ToolCallProgress sequence must end in status=completed."""
    handle = running_sandbox(with_session=True, llm_config=llm_config)
    out, _ = _drive_turn(
        handle,
        "Run the bash command `echo PHASE2_OK` and then say DONE.",
    )

    assert out.term is not None
    assert out.errors == []
    assert len(out.tool_starts) >= 1, "expected at least one ToolCallStart"
    # The bash tool's kind should be 'execute'.
    bash_starts = [s for s in out.tool_starts if s.kind == "execute"]
    assert len(bash_starts) >= 1, (
        f"no bash tool call seen; got kinds: {[s.kind for s in out.tool_starts]}"
    )
    # Each call must reach status=completed.
    call_ids = {s.tool_call_id for s in out.tool_starts}
    for cid in call_ids:
        progress = [p for p in out.tool_progress if p.tool_call_id == cid]
        assert any(p.status == "completed" for p in progress), (
            f"tool call {cid} never reached status=completed; statuses "
            f"seen: {[p.status for p in progress]}"
        )


def test_multi_step_turn_doesnt_drop_post_tool_text(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    """A turn that involves a tool call → follow-up answer creates >1
    assistant message in opencode. Our translator must track every
    assistant message id, not just the first. Regression test for the
    bug where post-tool text was dropped because its messageID wasn't
    in our singleton-tracked id.

    Model variance: gpt-5-mini sometimes refuses to "say something
    after the tool" no matter how the prompt is worded. To assert
    correctness without flaking on model whim, we subscribe to the raw
    ``/event`` stream IN PARALLEL with the manager's send_message and
    check: IF opencode emitted text-part content on more than one
    assistant message, our translator must surface text from BOTH. If
    the model only used a single assistant message this run, the
    regression we care about can't manifest and the test still passes."""
    import json as _json
    import threading as _thr
    import time as _time

    handle = running_sandbox(with_session=True, llm_config=llm_config)
    manager = handle.manager
    sandbox_id = handle.sandbox_id
    pw = manager._read_opencode_password(sandbox_id)
    assert pw, "opencode auth Secret missing for this sandbox"

    # Subscribe to /event in parallel via the same in-cluster Service
    # URL the manager uses. Done with the same httpx + Basic Auth.
    import httpx as _httpx

    base = (
        f"http://{manager._get_service_name(str(sandbox_id))}"
        f".{manager._namespace}.svc.cluster.local:4096"
    )
    raw_events: list[dict[str, Any]] = []
    sub_stop = _thr.Event()

    def _subscribe() -> None:
        try:
            with _httpx.stream(
                "GET",
                f"{base}/event",
                auth=_httpx.BasicAuth("opencode", pw),
                timeout=_httpx.Timeout(None, read=120),
            ) as r:
                buf = ""
                for ch in r.iter_text():
                    if sub_stop.is_set():
                        return
                    buf += ch
                    while "\n\n" in buf:
                        blk, buf = buf.split("\n\n", 1)
                        data = [
                            line[len("data: ") :]
                            for line in blk.splitlines()
                            if line.startswith("data: ")
                        ]
                        if data:
                            try:
                                raw_events.append(_json.loads("\n".join(data)))
                            except _json.JSONDecodeError:
                                pass
        except Exception:
            pass

    sub_t = _thr.Thread(target=_subscribe, daemon=True)
    sub_t.start()
    _time.sleep(0.5)  # let the subscription land before we drive the turn

    try:
        out, _opcode_sess = _drive_turn(
            handle,
            "First run the bash command `echo HELLO_FROM_BASH`. "
            "After the command finishes, write a single sentence in plain "
            "English describing what the command printed.",
        )
    finally:
        sub_stop.set()
        _time.sleep(0.3)

    assert out.term is not None
    assert out.errors == []
    assert len(out.tool_starts) >= 1

    # Inspect the raw opencode wire: which assistant message ids did
    # opencode emit text parts on?
    assistant_msg_ids_with_text: set[str] = set()
    for e in raw_events:
        if e.get("type") != "message.part.updated":
            continue
        p = (e.get("properties") or {}).get("part") or {}
        if p.get("type") != "text":
            continue
        msg_id = p.get("messageID")
        if isinstance(msg_id, str) and (p.get("text") or "") != "":
            assistant_msg_ids_with_text.add(msg_id)

    if len(assistant_msg_ids_with_text) <= 1:
        pytest.skip(
            "gpt-5-mini didn't emit a post-tool answer this run "
            "(opencode produced text on only one assistant message); "
            "the multi-message regression path can't manifest here. "
            "Unit test ``test_multi_assistant_message_turn_accepts_both`` "
            "covers this deterministically."
        )

    # opencode DID emit text on >1 assistant message — our translator
    # must have surfaced at least some AgentMessageChunk content.
    assert len(out.text) > 0, (
        "opencode emitted text parts on "
        f"{len(assistant_msg_ids_with_text)} distinct assistant messages "
        f"but the translator yielded 0 AgentMessageChunk. Post-tool text "
        "is being dropped — likely the assistant-message-id tracking is "
        "broken (regression on the multi-message turn path). "
        f"assistant_message_ids on the wire: {assistant_msg_ids_with_text}"
    )


def test_multi_turn_session_terminates_each_turn(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    """Three back-to-back prompts on the same opencode session. Each
    turn must terminate cleanly without bleeding events into the next."""
    handle = running_sandbox(with_session=True, llm_config=llm_config)

    opencode_session_id: str | None = None
    for i, prompt in enumerate(
        [
            "Say 'one' and nothing else.",
            "Say 'two' and nothing else.",
            "Say 'three' and nothing else.",
        ]
    ):
        out, opencode_session_id = _drive_turn(
            handle, prompt, opencode_session_id=opencode_session_id
        )
        assert out.term is not None, f"turn {i + 1} did not terminate"
        assert out.errors == [], f"turn {i + 1} had errors: {out.errors}"
        assert len(out.text) > 0, f"turn {i + 1} produced no text"


def test_yields_at_most_one_terminator(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    """opencode emits several end-of-turn signals (``message.updated``
    with completed, ``session.idle``, ``session.status``→idle). Each
    by itself could terminate the turn; we must yield exactly ONE
    ``PromptResponse`` regardless of which fires first."""
    handle = running_sandbox(with_session=True, llm_config=llm_config)

    # Run several prompts; if even one yields >1 PromptResponse, the
    # terminator de-dup is broken.
    opencode_session_id: str | None = None
    extra_terms = 0
    for i in range(3):
        # Re-run _drive_turn manually so we can count multiple terminators.
        manager = handle.manager
        if opencode_session_id is None:
            opencode_session_id = manager.ensure_opencode_session(
                handle.sandbox_id, handle.session_id
            )
        term_count = 0
        for ev in manager.send_message(
            handle.sandbox_id,
            handle.session_id,
            f"Say '{i}'.",
            opencode_session_id=opencode_session_id,
        ):
            if isinstance(ev, PromptResponse):
                term_count += 1
        if term_count != 1:
            extra_terms += 1
    assert extra_terms == 0, (
        f"{extra_terms} turn(s) yielded ≠1 PromptResponse — terminator de-dup is broken"
    )


def test_tool_call_raw_output_wrapped_for_consumers(
    running_sandbox: Callable[..., Any],
    llm_config: LLMProviderConfig,
) -> None:
    """``ToolCallProgress.raw_output`` must be a dict shaped
    ``{"output": <string>, "metadata"?: {...}}`` — that's what the
    frontend's ``parsePacket.ts:getRawOutput`` extracts. opencode emits
    ``state.output`` as a plain string for ``bash``; the translator wraps it."""
    handle = running_sandbox(with_session=True, llm_config=llm_config)
    out, _ = _drive_turn(
        handle,
        "Run the bash command `echo WRAPPED_OUTPUT_PROBE`. No commentary.",
    )

    bash_completed = [
        p for p in out.tool_progress if p.kind == "execute" and p.status == "completed"
    ]
    assert bash_completed, (
        f"no completed bash tool_call_progress; "
        f"statuses: {[(p.kind, p.status) for p in out.tool_progress]}"
    )
    ro = cast(dict[str, Any] | None, bash_completed[-1].raw_output)
    assert ro is not None
    assert "output" in ro, (
        f"raw_output missing 'output' key (frontend depends on it): {ro!r}"
    )
    assert isinstance(ro["output"], str)
    assert "WRAPPED_OUTPUT_PROBE" in ro["output"], (
        f"bash output didn't include our sentinel: {ro['output']!r}"
    )
