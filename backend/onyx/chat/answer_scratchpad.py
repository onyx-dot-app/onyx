from __future__ import annotations

import asyncio
import contextvars
import json
import os
import queue
import threading
from collections.abc import Generator
from collections.abc import Iterator
from dataclasses import dataclass
from queue import Queue
from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Optional

import litellm
from agents import Agent
from agents import AgentHooks
from agents import function_tool
from agents import ModelSettings
from agents import RunContextWrapper
from agents import Runner
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions.models.litellm_model import LitellmModel
from agents.handoffs import HandoffInputData
from agents.stream_events import RawResponsesStreamEvent
from agents.stream_events import RunItemStreamEvent
from braintrust import traced
from openai.types import Reasoning
from pydantic import BaseModel

from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.dr_prompt_builder import (
    get_dr_prompt_orchestration_templates,
)
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.exa_client import (
    ExaClient,
)
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.llm.interfaces import (
    LLM,
)
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass
class RunDependencies:
    emitter: Emitter
    llm: LLM
    search_tool: SearchTool | None = None


@dataclass
class MyContext:
    """Context class to hold search tool and other dependencies"""

    run_dependencies: RunDependencies | None = None
    needs_compaction: bool = False


def short_tag(link: str, i: int) -> str:
    # Stable, readable; index keeps it deterministic across a batch
    return f"S{i+1}"


@function_tool
def web_search(query: str) -> str:
    """Search the web for information. This tool provides urls and short snippets,
    but does not fetch the full content of the urls."""
    exa_client = ExaClient()
    hits = exa_client.search(query)
    results = []
    for i, r in enumerate(hits):
        results.append(
            {
                "tag": short_tag(r.link, i),  # <-- add a tag
                "title": r.title,
                "link": r.link,
                "snippet": r.snippet,
                "author": r.author,
                "published_date": (
                    r.published_date.isoformat() if r.published_date else None
                ),
            }
        )
    return json.dumps({"results": results})


@function_tool
def web_fetch(urls: List[str]) -> str:
    """Fetch the full contents of a list of URLs."""
    exa_client = ExaClient()
    docs = exa_client.contents(urls)
    out = []
    for i, d in enumerate(docs):
        out.append(
            {
                "tag": short_tag(d.link, i),  # <-- add a tag
                "title": d.title,
                "link": d.link,
                "full_content": d.full_content,
                "published_date": (
                    d.published_date.isoformat() if d.published_date else None
                ),
            }
        )
    return json.dumps({"results": out})


@traced(name="llm_completion", type="llm")
def llm_completion(
    model_name: str,
    temperature: float,
    messages: List[Dict[str, Any]],
    stream: bool = False,
) -> litellm.ModelResponse:
    return litellm.responses(
        model=model_name,
        input=messages,
        tools=[],
        stream=stream,
        reasoning=litellm.Reasoning(effort="medium", summary="detailed"),
    )


@function_tool
def internal_search(context_wrapper: RunContextWrapper[MyContext], query: str) -> str:
    """Search internal company vector database for information. Sources
    include:
    - Fireflies (internal company call transcripts)
    - Google Drive (internal company documents)
    - Gmail (internal company emails)
    - Linear (internal company issues)
    - Slack (internal company messages)
    """
    context_wrapper.context.run_dependencies.emitter.emit(
        kind="tool-progress", data={"progress": "Searching internal database"}
    )
    search_tool = context_wrapper.context.run_dependencies.search_tool
    if search_tool is None:
        raise RuntimeError("Search tool not available in context")

    with get_session_with_current_tenant() as search_db_session:
        for tool_response in search_tool.run(
            query=query,
            override_kwargs=SearchToolOverrideKwargs(
                force_no_rerank=True,
                alternate_db_session=search_db_session,
                skip_query_analysis=True,
                original_query=query,
            ),
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections

                break
    return retrieved_docs


def _convert_to_packet_obj(packet: Dict[str, Any]) -> Any | None:
    """Convert a packet dictionary to PacketObj when possible.

    Args:
        packet: Dictionary containing packet data

    Returns:
        PacketObj instance if conversion is possible, None otherwise
    """
    if not isinstance(packet, dict) or "type" not in packet:
        return None

    packet_type = packet.get("type")
    if not packet_type:
        return None

    try:
        # Import here to avoid circular imports
        from onyx.server.query_and_chat.streaming_models import (
            MessageStart,
            MessageDelta,
            OverallStop,
        )

        if packet_type == "response.output_item.added":
            return MessageStart(
                type="message_start",
                content="",
                final_documents=None,
            )
        elif packet_type == "response.output_text.delta":
            return MessageDelta(type="message_delta", content=packet["delta"])
        elif packet_type == "response.completed":
            return OverallStop(type="stop")

    except Exception as e:
        # Log the error but don't fail the entire process
        logger.debug(f"Failed to convert packet to PacketObj: {e}")

    return None


# stream_bus.py
@dataclass
class StreamPacket:
    kind: str  # "agent" | "tool-progress" | "done"
    payload: Dict[str, Any] = None


class Emitter:
    """Use this inside tools to emit arbitrary UI progress."""

    def __init__(self, bus: Queue):
        self.bus = bus

    def emit(self, kind: str, data: Dict[str, Any]) -> None:
        self.bus.put(StreamPacket(kind=kind, payload=data))


# If we want durable execution in the future, we can replace this with a temporal call
def start_run_in_thread(
    agent: Agent,
    messages: List[Dict[str, Any]],
    cfg: GraphConfig,
    llm: LLM,
    emitter: Emitter,
    search_tool: SearchTool | None = None,
) -> threading.Thread:
    def worker():
        async def amain():
            ctx = MyContext(
                run_dependencies=RunDependencies(
                    search_tool=search_tool,
                    emitter=emitter,
                    llm=llm,
                )
            )
            # 1) start the streamed run (async)
            streamed = Runner.run_streamed(agent, messages, context=ctx)

            # 2) forward the agent’s async event stream
            async for ev in streamed.stream_events():
                if isinstance(ev, RunItemStreamEvent):
                    pass
                elif isinstance(ev, RawResponsesStreamEvent):
                    emitter.emit(kind="agent", data=ev.data.model_dump())

            emitter.emit(kind="done", data={"ok": True})

        # run the async main inside this thread
        asyncio.run(amain())

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


class ResearchScratchpad(BaseModel):
    notes: List[dict] = []


scratchpad = ResearchScratchpad()


@function_tool
def add_note(note: str, source_url: str | None = None):
    """Store a factual note you want to cite later."""
    scratchpad.notes.append({"note": note, "source_url": source_url})
    return {"ok": True, "count": len(scratchpad.notes)}


@function_tool
def finalize_report():
    """Signal you're done researching. Return a structured, citation-rich report."""
    # The model should *compose* the report as the tool *result*, using notes in scratchpad.
    # Some teams have the model return the full report as this tool's return value
    # so the UI can detect completion cleanly.
    return {
        "status": "ready_to_render",
        "notes_index": scratchpad.notes,  # the model can read these to assemble citations
    }


class CompactionHooks(AgentHooks[Any]):
    async def on_llm_start(
        self,
        context: RunContextWrapper[MyContext],
        agent: Agent[Any],
        system_prompt: Optional[str],
        input_items: List[dict],
    ) -> None:
        print(f"[{agent.name}] LLM start")
        print("system_prompt:", system_prompt)
        print("usage so far:", context.usage.total_tokens)
        usage = context.usage.total_tokens
        if usage > 10000:
            context.context.needs_compaction = True


def compaction_input_filter(input_data: HandoffInputData):
    filtered_messages = []
    for msg in input_data.input_history[:-1]:
        if isinstance(msg, dict) and msg.get("content") is not None:
            # Convert tool messages to user messages to avoid API errors
            if msg.get("role") == "tool":
                filtered_msg = {
                    "role": "user",
                    "content": f"Tool response: {msg.get('content', '')}",
                }
                filtered_messages.append(filtered_msg)
            else:
                filtered_messages.append(msg)

    # Only proceed with compaction if we have valid messages
    if filtered_messages:
        return [filtered_messages[-1]]


def construct_deep_research_agent(llm: LLM) -> Agent:
    litellm_model = LitellmModel(
        # If you have access, prefer OpenAI’s deep research-capable models:
        # "o3-deep-research" or "o4-mini-deep-research"
        # otherwise keep your current model and lean on the prompt + tools
        model=llm.config.model_name,
        api_key=llm.config.api_key,
    )

    DR_INSTRUCTIONS = f"""
    {RECOMMENDED_PROMPT_PREFIX}
You are a deep-research agent. Work in explicit iterations:
1) PLAN: Decompose the user’s query into sub-questions and a step-by-step plan.
2) SEARCH: Use web_search to explore multiple angles, fanning out and searching in parallel.
3) FETCH: Use web_fetch for any promising URLs to extract specifics and quotes.
4) NOTE: After each useful find, call add_note(note, source_url) to save key facts.
5) REVISE: If evidence contradicts earlier assumptions, update your plan and continue.
6) FINALIZE: When confident, call finalize_report(). Your final answer must include:
   - Clear, structured conclusions
   - A short “How I searched” summary
   - Inline citations to sources (with URLs)
   - A bullet list of limitations/open questions
Guidelines:
- Prefer breadth-first exploration before deep dives.
- Compare sources and dates; prioritize recency for time-sensitive topics.
- Minimize redundancy by skimming before fetching.
- Think out loud in a compact way, but keep reasoning crisp.
- If context exceeds 10000 tokens, handoff to the compactor agent.
"""
    return Agent(
        name="Researcher",
        instructions=DR_INSTRUCTIONS,
        model=litellm_model,
        tools=[web_search, web_fetch, add_note, finalize_report, internal_search],
        model_settings=ModelSettings(
            temperature=llm.config.temperature,
            include_usage=True,
            parallel_tool_calls=True,
            # optional: let model choose tools freely
            # tool_choice="auto",  # if supported by your LitellmModel wrapper
        ),
        hooks=CompactionHooks(),
    )


def unified_event_stream(
    messages: List[Dict[str, Any]],
    cfg: GraphConfig,
    llm: LLM,
    emitter: Emitter,
    search_tool: SearchTool | None = None,
) -> Generator[Dict[str, Any], None, None]:
    bus: Queue = Queue()
    emitter = Emitter(bus)
    current_context = contextvars.copy_context()
    t = threading.Thread(
        target=current_context.run,
        args=(
            # thread_worker_dr_turn,
            thread_worker_simple_turn,
            messages,
            cfg,
            llm,
            emitter,
            search_tool,
        ),  # eval_context=None for now
        daemon=True,
    )
    t.start()
    done = False
    while not done:
        pkt: StreamPacket = emitter.bus.get()
        if pkt.kind == "done":
            done = True
        else:
            # Convert packet to PacketObj when possible
            packet_obj = _convert_to_packet_obj(pkt.payload)
            if packet_obj:
                # Convert PacketObj back to dict for compatibility
                yield packet_obj.model_dump()
            else:
                # Fallback to original payload
                yield pkt.payload


# This should be close to the API
def stream_chat_sync(
    messages: List[Dict[str, Any]],
    cfg: GraphConfig,
    llm: LLM,
    search_tool: SearchTool | None = None,
) -> Generator[Dict[str, Any], None, None]:
    bus: Queue = Queue()
    emitter = Emitter(bus)
    return unified_event_stream(
        messages=messages,
        cfg=cfg,
        llm=llm,
        emitter=emitter,
        search_tool=search_tool,
    )


def construct_simple_agent(
    llm: LLM,
) -> Agent:
    litellm_model = LitellmModel(
        model="o3-mini",
        api_key=llm.config.api_key,
    )
    return Agent(
        name="Assistant",
        instructions="""
        You are a helpful assistant that can search the web, fetch content from URLs,
        and search internal databases. Please do some reasoning and then return your answer.
        """,
        model=litellm_model,
        tools=[web_search, web_fetch, internal_search],
        model_settings=ModelSettings(
            temperature=0.0,
            include_usage=True,  # Track usage metrics
            reasoning=Reasoning(
                effort="medium", summary="detailed", generate_summary="detailed"
            ),
            verbose=True,
        ),
    )


def thread_worker_dr_turn(messages, cfg, llm, emitter, search_tool):
    """
    Worker function for deep research turn that runs in a separate thread.

    Args:
        messages: List of messages for the conversation
        cfg: Graph configuration
        llm: Language model instance
        emitter: Event emitter for streaming responses
        search_tool: Search tool instance (optional)
        eval_context: Evaluation context to be propagated to the worker thread
    """
    try:
        dr_turn(messages, cfg, llm, emitter, search_tool)
    except Exception as e:
        logger.error(f"Error in dr_turn: {e}", exc_info=e, stack_info=True)
        emitter.emit(kind="done", data={"ok": False})


def thread_worker_simple_turn(messages, cfg, llm, emitter, search_tool):
    try:
        simple_turn(
            messages=messages,
            cfg=cfg,
            llm=llm,
            turn_event_stream_emitter=emitter,
            search_tool=search_tool,
        )
    except Exception as e:
        logger.error(f"Error in simple_turn: {e}", exc_info=e, stack_info=True)
        emitter.emit(kind="done", data={"ok": False})


SENTINEL = object()


class StreamBridge:
    """
    Spins up an asyncio loop in a background thread, starts Runner.run_streamed there,
    consumes its async event stream, and exposes a blocking .events() iterator.
    """

    def __init__(self, agent, messages, ctx, max_turns: int = 100):
        self.agent = agent
        self.messages = messages
        self.ctx = ctx
        self.max_turns = max_turns

        self._q: "queue.Queue[object]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._streamed = None

    def start(self):
        def worker():
            async def run_and_consume():
                # Create the streamed run *inside* the loop thread
                self._streamed = Runner.run_streamed(
                    self.agent,
                    self.messages,
                    context=self.ctx,
                    max_turns=self.max_turns,
                )
                try:
                    async for ev in self._streamed.stream_events():
                        self._q.put(ev)
                finally:
                    self._q.put(SENTINEL)

            # Each thread needs its own loop
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(run_and_consume())
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return self

    def events(self) -> Iterator[object]:
        while True:
            ev = self._q.get()
            if ev is SENTINEL:
                break
            yield ev

    def cancel(self):
        # Post a cancellation to the loop thread safely
        if self._loop and self._streamed:

            def _do_cancel():
                try:
                    self._streamed.cancel()
                except Exception:
                    pass

            self._loop.call_soon_threadsafe(_do_cancel)


def simple_turn(
    messages: List[Dict[str, Any]],
    cfg: GraphConfig,
    llm: LLM,
    turn_event_stream_emitter: Emitter,
    search_tool: SearchTool | None = None,
) -> None:
    llm_response = llm_completion(
        model_name="gpt-5-mini",
        temperature=0.0,
        messages=messages,
        stream=True,
    )
    llm_response.json()
    simple_agent = construct_simple_agent(llm)
    ctx = MyContext(
        run_dependencies=RunDependencies(
            search_tool=search_tool, emitter=turn_event_stream_emitter, llm=llm
        )
    )
    bridge = StreamBridge(simple_agent, messages, ctx, max_turns=100).start()
    for ev in bridge.events():
        if isinstance(ev, RunItemStreamEvent):
            print("RUN ITEM STREAM EVENT!")
            if ev.name == "reasoning_item_created":
                print("REASONING!")
                turn_event_stream_emitter.emit(
                    kind="reasoning", data=ev.item.raw_item.model_dump()
                )
        elif isinstance(ev, RawResponsesStreamEvent):
            print("RAW RESPONSES STREAM EVENT!")
            print(ev.type)
            turn_event_stream_emitter.emit(kind="agent", data=ev.data.model_dump())
    turn_event_stream_emitter.emit(kind="done", data={"ok": True})


def dr_turn(
    messages: List[Dict[str, Any]],
    cfg: GraphConfig,
    llm: LLM,
    turn_event_stream_emitter: Emitter,  # TurnEventStream is the primary output of the turn
    search_tool: SearchTool | None = None,
) -> None:
    """
    Execute a deep research turn with evaluation context support.

    Args:
        messages: List of messages for the conversation
        cfg: Graph configuration
        llm: Language model instance
        turn_event_stream_emitter: Event emitter for streaming responses
        search_tool: Search tool instance (optional)
        eval_context: Evaluation context for the turn (optional)
    """
    clarification = get_clarification(
        messages, cfg, llm, turn_event_stream_emitter, search_tool
    )
    output = json.loads(clarification.choices[0].message.content)
    clarification_output = ClarificationOutput(**output)
    if clarification_output.clarification_needed:
        turn_event_stream_emitter.emit(
            kind="agent", data=clarification_output.clarification_question
        )
        turn_event_stream_emitter.emit(kind="done", data={"ok": True})
        return
    dr_agent = construct_deep_research_agent(llm)
    ctx = MyContext(
        run_dependencies=RunDependencies(
            search_tool=search_tool,
            emitter=turn_event_stream_emitter,
            llm=llm,
        )
    )
    bridge = StreamBridge(dr_agent, messages, ctx, max_turns=100).start()
    for ev in bridge.events():
        if isinstance(ev, RunItemStreamEvent):
            pass
        elif isinstance(ev, RawResponsesStreamEvent):
            turn_event_stream_emitter.emit(kind="agent", data=ev.data.model_dump())

    turn_event_stream_emitter.emit(kind="done", data={"ok": True})


class ClarificationOutput(BaseModel):
    clarification_question: str
    clarification_needed: bool


def get_clarification(
    messages: List[Dict[str, Any]],
    cfg: GraphConfig,
    llm: LLM,
    emitter: Emitter,
    search_tool: SearchTool | None = None,
) -> litellm.ModelResponse:
    chat_history_string = (
        get_chat_history_string(
            cfg.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )
    base_clarification_prompt = get_dr_prompt_orchestration_templates(
        DRPromptPurpose.CLARIFICATION,
        research_type=ResearchType.DEEP,
        entity_types_string=None,
        relationship_types_string=None,
        available_tools={},
    )
    clarification_prompt = base_clarification_prompt.build(
        question=messages[-1]["content"],
        chat_history_string=chat_history_string,
    )
    clarifier_prompt = prompt_with_handoff_instructions(clarification_prompt)
    llm_response = llm_completion(
        model_name=llm.config.model_name,
        temperature=llm.config.temperature,
        messages=[{"role": "user", "content": clarifier_prompt}],
        stream=False,
    )
    return llm_response


if __name__ == "__main__":
    messages = [
        {
            "role": "user",
            "content": """
            Let $N$ denote the number of ordered triples of positive integers $(a, b, c)$ such that $a, b, c
            \\leq 3^6$ and $a^3 + b^3 + c^3$ is a multiple of $3^7$. Find the remainder when $N$ is divided by $1000$.
            """,
        }
    ]
    # OpenAI reasoning is not supported yet due to: https://github.com/BerriAI/litellm/pull/14117
    reasoning_agent = Agent(
        name="Reasoning",
        instructions="You are a reasoning agent. You are given a question and you need to reason about it.",
        model=LitellmModel(
            model="gpt-5-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
        ),
        tools=[],
        model_settings=ModelSettings(
            temperature=0.0,
            reasoning=Reasoning(effort="medium", summary="detailed"),
        ),
    )
    llm_response = llm_completion(
        model_name="gpt-5-mini",
        temperature=0.0,
        messages=messages,
        stream=False,
    )
    x = llm_response.json()
    print(x)
