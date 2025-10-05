from agents import Agent
from agents import ModelSettings

from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.turn.infra.chat_turn_event_stream import OnyxRunner
from onyx.chat.turn.infra.chat_turn_orchestration import unified_event_stream
from onyx.chat.turn.infra.packet_translation import default_packet_translation
from onyx.chat.turn.infra.session_sink import extract_final_answer_from_packets
from onyx.chat.turn.infra.session_sink import save_iteration
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.chat.turn.models import MyContext
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.threadpool_concurrency import wait_on_background


@unified_event_stream
def fast_chat_turn(messages: list[dict], dependencies: ChatTurnDependencies) -> None:
    ctx = MyContext(
        run_dependencies=dependencies,
        aggregated_context=AggregatedDRContext(
            context="context",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],  # TODO: the only field that matters for now
        ),
        iteration_instructions=[],
    )
    agent = Agent(
        name="Assistant",
        model=dependencies.llm_model,
        tools=dependencies.tools,
        model_settings=ModelSettings(
            temperature=0.0,
            include_usage=True,
        ),
    )
    bridge, thread = OnyxRunner().run_streamed_in_background(
        agent, messages, context=ctx, max_turns=100
    )
    for ev in bridge.events():
        if not is_connected(
            dependencies.dependencies_to_maybe_remove.chat_session_id,
            dependencies.redis_client,
        ):
            _emit_clean_up_packets(dependencies, ctx)
            bridge.cancel()
            break
        ctx.current_run_step
        obj = default_packet_translation(ev)
        if obj:
            dependencies.emitter.emit(Packet(ind=ctx.current_run_step, obj=obj))
    save_iteration(
        db_session=dependencies.db_session,
        message_id=dependencies.dependencies_to_maybe_remove.message_id,
        chat_session_id=dependencies.dependencies_to_maybe_remove.chat_session_id,
        research_type=dependencies.dependencies_to_maybe_remove.research_type,
        ctx=ctx,
        final_answer=extract_final_answer_from_packets(
            dependencies.emitter.packet_history
        ),
        all_cited_documents=[],
    )
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=OverallStop(type="stop"))
    )
    wait_on_background(thread)


# TODO: Maybe in general there's a cleaner way to handle cancellation in the middle of a tool call?
def _emit_clean_up_packets(dependencies: ChatTurnDependencies, ctx: MyContext) -> None:
    # Tool call / reasoning cancelled
    if dependencies.emitter.packet_history[-1].obj.type != "message_delta":
        dependencies.emitter.emit(
            Packet(
                ind=ctx.current_run_step,
                obj=MessageStart(
                    type="message_start", content="Cancelled", final_documents=None
                ),
            )
        )
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=SectionEnd(type="section_end"))
    )
