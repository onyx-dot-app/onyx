from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import GraphInputs
from onyx.agents.agent_search.models import GraphPersistence
from onyx.agents.agent_search.models import GraphSearchConfig
from onyx.agents.agent_search.models import GraphTooling
from onyx.agents.agent_search.run_graph import run_dr_graph
from onyx.chat.models import AnswerStream
from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.agent_configs import AGENT_ALLOW_REFINEMENT
from onyx.configs.agent_configs import INITIAL_SEARCH_DECOMPOSITION_ENABLED
from onyx.configs.agent_configs import TF_DR_DEFAULT_FAST
from onyx.context.search.models import RerankingDetails
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.models import Persona
from onyx.file_store.utils import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.gpu_utils import fast_gpu_status_request
from onyx.utils.logger import setup_logger

logger = setup_logger()


class Answer:
    def __init__(
        self,
        prompt_builder: AnswerPromptBuilder,
        answer_style_config: AnswerStyleConfig,
        llm: LLM,
        fast_llm: LLM,
        force_use_tool: ForceUseTool,
        persona: Persona | None,
        rerank_settings: RerankingDetails | None,
        chat_session_id: UUID,
        current_agent_message_id: int,
        db_session: Session,
        # newly passed in files to include as part of this question
        # TODO THIS NEEDS TO BE HANDLED
        latest_query_files: list[InMemoryChatFile] | None = None,
        tools: list[Tool] | None = None,
        # NOTE: for native tool-calling, this is only supported by OpenAI atm,
        #       but we only support them anyways
        # if set to True, then never use the LLMs provided tool-calling functonality
        skip_explicit_tool_calling: bool = False,
        skip_gen_ai_answer_generation: bool = False,
        is_connected: Callable[[], bool] | None = None,
        use_agentic_search: bool = False,
        research_type: ResearchType | None = None,
        research_plan: dict[str, Any] | None = None,
        project_instructions: str | None = None,
    ) -> None:
        self.is_connected: Callable[[], bool] | None = is_connected
        self._processed_stream: list[AnswerStreamPart] | None = None
        self._is_cancelled = False

        search_tools = [tool for tool in (tools or []) if isinstance(tool, SearchTool)]
        search_tool: SearchTool | None = None

        if len(search_tools) > 1:
            # TODO: handle multiple search tools
            raise ValueError("Multiple search tools found")
        elif len(search_tools) == 1:
            search_tool = search_tools[0]

        using_tool_calling_llm = (
            explicit_tool_calling_supported(
                llm.config.model_provider, llm.config.model_name
            )
            and not skip_explicit_tool_calling
        )

        using_cloud_reranking = (
            rerank_settings is not None
            and rerank_settings.rerank_provider_type is not None
        )
        allow_agent_reranking = using_cloud_reranking or fast_gpu_status_request(
            indexing=False
        )

        self.graph_inputs = GraphInputs(
            persona=persona,
            rerank_settings=rerank_settings,
            prompt_builder=prompt_builder,
            files=latest_query_files,
            structured_response_format=answer_style_config.structured_response_format,
            project_instructions=project_instructions,
        )
        self.graph_tooling = GraphTooling(
            primary_llm=llm,
            fast_llm=fast_llm,
            search_tool=search_tool,
            tools=tools or [],
            force_use_tool=force_use_tool,
            using_tool_calling_llm=using_tool_calling_llm,
        )
        self.graph_persistence = GraphPersistence(
            db_session=db_session,
            chat_session_id=chat_session_id,
            message_id=current_agent_message_id,
        )

        if use_agentic_search:
            research_type = ResearchType.DEEP
        elif TF_DR_DEFAULT_FAST:
            research_type = ResearchType.FAST
        else:
            research_type = ResearchType.THOUGHTFUL

        self.search_behavior_config = GraphSearchConfig(
            use_agentic_search=use_agentic_search,
            skip_gen_ai_answer_generation=skip_gen_ai_answer_generation,
            allow_refinement=AGENT_ALLOW_REFINEMENT,
            allow_agent_reranking=allow_agent_reranking,
            perform_initial_search_decomposition=INITIAL_SEARCH_DECOMPOSITION_ENABLED,
            kg_config_settings=get_kg_config_settings(),
            research_type=research_type,
        )
        self.graph_config = GraphConfig(
            inputs=self.graph_inputs,
            tooling=self.graph_tooling,
            persistence=self.graph_persistence,
            behavior=self.search_behavior_config,
        )

    @property
    def processed_streamed_output(self) -> AnswerStream:
        if self._processed_stream is not None:
            yield from self._processed_stream
            return

        # TODO: add toggle in UI with customizable TimeBudget
        stream = run_dr_graph(self.graph_config)

        processed_stream: list[AnswerStreamPart] = []
        for packet in stream:
            if self.is_cancelled():
                packet = StreamStopInfo(stop_reason=StreamStopReason.CANCELLED)
                yield packet
                break
            processed_stream.append(packet)
            yield packet
        self._processed_stream = processed_stream

    @property
    def citations(self) -> list[CitationInfo]:
        citations: list[CitationInfo] = []
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo) and packet.level is None:
                citations.append(packet)

        return citations

    def is_cancelled(self) -> bool:
        if self._is_cancelled:
            return True

        if self.is_connected is not None:
            if not self.is_connected():
                logger.debug("Answer stream has been cancelled")
            self._is_cancelled = not self.is_connected()

        return self._is_cancelled
