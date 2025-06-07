from collections import defaultdict
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import GraphInputs
from onyx.agents.agent_search.models import GraphPersistence
from onyx.agents.agent_search.models import GraphSearchConfig
from onyx.agents.agent_search.models import GraphTooling
from onyx.agents.agent_search.run_graph import run_agent_search_graph
from onyx.agents.agent_search.run_graph import run_basic_graph
from onyx.agents.agent_search.run_graph import run_dc_graph
from onyx.agents.agent_search.run_graph import run_kb_graph
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import AnswerPacket
from onyx.chat.models import AnswerStream
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationInfo
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import SubQuestionKey
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.agent_configs import AGENT_ALLOW_REFINEMENT
from onyx.configs.agent_configs import INITIAL_SEARCH_DECOMPOSITION_ENABLED
from onyx.configs.chat_configs import USE_DIV_CON_AGENT
from onyx.configs.constants import BASIC_KEY
from onyx.context.search.models import RerankingDetails
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.models import Persona
from onyx.file_store.utils import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.gpu_utils import fast_gpu_status_request
from onyx.utils.logger import setup_logger

logger = setup_logger()

BASIC_SQ_KEY = SubQuestionKey(level=BASIC_KEY[0], question_num=BASIC_KEY[1])


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
    ) -> None:
        self.is_connected: Callable[[], bool] | None = is_connected
        self._processed_stream: list[AnswerPacket] | None = None
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
        self.search_behavior_config = GraphSearchConfig(
            use_agentic_search=use_agentic_search,
            skip_gen_ai_answer_generation=skip_gen_ai_answer_generation,
            allow_refinement=AGENT_ALLOW_REFINEMENT,
            allow_agent_reranking=allow_agent_reranking,
            perform_initial_search_decomposition=INITIAL_SEARCH_DECOMPOSITION_ENABLED,
            kg_config_settings=get_kg_config_settings(db_session),
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

        if self.graph_config.behavior.use_agentic_search and (
            self.graph_config.inputs.persona
            and self.graph_config.behavior.kg_config_settings.KG_ENABLED
            and self.graph_config.inputs.persona.name.startswith("KG Dev")
        ):
            run_langgraph = run_kb_graph
        elif self.graph_config.behavior.use_agentic_search:
            run_langgraph = run_agent_search_graph
        elif (
            self.graph_config.inputs.persona
            and USE_DIV_CON_AGENT
            and self.graph_config.inputs.persona.description.startswith(
                "DivCon Beta Agent"
            )
        ):
            run_langgraph = run_dc_graph
        else:
            run_langgraph = run_basic_graph

        stream = run_langgraph(
            self.graph_config,
        )

        processed_stream = []
        for packet in stream:
            if self.is_cancelled():
                packet = StreamStopInfo(stop_reason=StreamStopReason.CANCELLED)
                yield packet
                break
            processed_stream.append(packet)
            yield packet
        self._processed_stream = processed_stream

    @property
    def llm_answer(self) -> str:
        answer = ""
        for packet in self.processed_streamed_output:
            # handle basic answer flow, plus level 0 agent answer flow
            # since level 0 is the first answer the user sees and therefore the
            # child message of the user message in the db (so it is handled
            # like a basic flow answer)
            if (isinstance(packet, OnyxAnswerPiece) and packet.answer_piece) or (
                isinstance(packet, AgentAnswerPiece)
                and packet.answer_piece
                and packet.answer_type == "agent_level_answer"
                and packet.level == 0
            ):
                answer += packet.answer_piece

        return answer

    def llm_answer_by_level(self) -> dict[int, str]:
        answer_by_level: dict[int, str] = defaultdict(str)
        for packet in self.processed_streamed_output:
            if (
                isinstance(packet, AgentAnswerPiece)
                and packet.answer_piece
                and packet.answer_type == "agent_level_answer"
            ):
                assert packet.level is not None
                answer_by_level[packet.level] += packet.answer_piece
            elif isinstance(packet, OnyxAnswerPiece) and packet.answer_piece:
                answer_by_level[BASIC_KEY[0]] += packet.answer_piece
        return answer_by_level

    @property
    def citations(self) -> list[CitationInfo]:
        citations: list[CitationInfo] = []
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo) and packet.level is None:
                citations.append(packet)

        return citations

    def citations_by_subquestion(self) -> dict[SubQuestionKey, list[CitationInfo]]:
        citations_by_subquestion: dict[SubQuestionKey, list[CitationInfo]] = (
            defaultdict(list)
        )
        basic_subq_key = SubQuestionKey(level=BASIC_KEY[0], question_num=BASIC_KEY[1])
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo):
                if packet.level_question_num is not None and packet.level is not None:
                    citations_by_subquestion[
                        SubQuestionKey(
                            level=packet.level, question_num=packet.level_question_num
                        )
                    ].append(packet)
                elif packet.level is None:
                    citations_by_subquestion[basic_subq_key].append(packet)
        return citations_by_subquestion

    def is_cancelled(self) -> bool:
        if self._is_cancelled:
            return True

        if self.is_connected is not None:
            if not self.is_connected():
                logger.debug("Answer stream has been cancelled")
            self._is_cancelled = not self.is_connected()

        return self._is_cancelled
