import json
from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import MAX_AGENT_RECURSION_DEPTH
from onyx.context.search.models import SavedSearchDoc
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.streaming_models import AgentToolDelta
from onyx.server.query_and_chat.streaming_models import AgentToolFinal
from onyx.server.query_and_chat.streaming_models import AgentToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.agent.models import AgentInvocationConfig
from onyx.tools.tool_implementations.agent.models import AgentToolOverrideKwargs
from onyx.utils.logger import setup_logger

logger = setup_logger()


AGENT_TOOL_ID_OFFSET = 1000000


def generate_agent_tool_id(parent_persona_id: int, child_persona_id: int) -> int:
    return AGENT_TOOL_ID_OFFSET + (parent_persona_id * 10000) + child_persona_id


class AgentTool(Tool[AgentToolOverrideKwargs]):
    NAME_PREFIX = "invoke_agent_"

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        child_persona: Persona,
        parent_persona_id: int,
        agent_config: AgentInvocationConfig,
        db_session: Session,
        user: User | None,
        llm: LLM,
        fast_llm: LLM,
    ):
        super().__init__(emitter)
        self._tool_id = tool_id
        self._child_persona = child_persona
        self._parent_persona_id = parent_persona_id
        self._config = agent_config
        self._db_session = db_session
        self._user = user
        self._llm = llm
        self._fast_llm = fast_llm
        self._collected_search_queries: list[str] = []
        self._collected_search_docs: list = []
        self._nested_agent_runs: list[dict] = []

    @property
    def id(self) -> int:
        return self._tool_id

    @property
    def name(self) -> str:
        safe_name = self._child_persona.name.lower().replace(" ", "_").replace("-", "_")
        return f"{self.NAME_PREFIX}{safe_name}"

    @property
    def description(self) -> str:
        base_desc = f"Invoke the '{self._child_persona.name}' agent to help with tasks."
        if self._child_persona.description:
            base_desc += (
                f" This agent specializes in: {self._child_persona.description}"
            )
        if self._config.invocation_instructions:
            base_desc += f" Use this agent when: {self._config.invocation_instructions}"
        return base_desc

    @property
    def display_name(self) -> str:
        return f"Agent: {self._child_persona.name}"

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The specific task or question to delegate to this agent",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context or background information for the agent (optional)",
                        },
                    },
                    "required": ["task"],
                },
            },
        }

    def emit_start(self, turn_index: int) -> None:
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=AgentToolStart(
                    agent_name=self._child_persona.name,
                    agent_id=self._child_persona.id,
                ),
            )
        )

    def _get_tool_override_kwargs(self, tool: Tool, task: str) -> Any:
        from onyx.tools.models import (
            ChatMinimalTextMessage,
            OpenURLToolOverrideKwargs,
            SearchToolOverrideKwargs,
            WebSearchToolOverrideKwargs,
        )
        from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
        from onyx.tools.tool_implementations.search.search_tool import SearchTool
        from onyx.tools.tool_implementations.web_search.web_search_tool import (
            WebSearchTool,
        )
        from onyx.configs.constants import MessageType

        if isinstance(tool, OpenURLTool):
            return OpenURLToolOverrideKwargs(
                starting_citation_num=1,
                citation_mapping={},
            )
        elif isinstance(tool, SearchTool):
            minimal_history = [
                ChatMinimalTextMessage(
                    message=task,
                    message_type=MessageType.USER,
                )
            ]
            return SearchToolOverrideKwargs(
                starting_citation_num=1,
                original_query=task,
                message_history=minimal_history,
            )
        elif isinstance(tool, WebSearchTool):
            return WebSearchToolOverrideKwargs(
                starting_citation_num=1,
            )
        return None

    def _build_child_tools(self) -> list[Tool]:
        """Build the child agent's tools (excluding AgentTools to prevent infinite recursion)."""
        from onyx.tools.tool_constructor import construct_tools, SearchToolConfig

        tool_dict = construct_tools(
            persona=self._child_persona,
            db_session=self._db_session,
            emitter=self.emitter,
            user=self._user,
            llm=self._llm,
            fast_llm=self._fast_llm,
            search_tool_config=SearchToolConfig(),
            disable_internal_search=False,
        )

        tools: list[Tool] = []
        for tool_list in tool_dict.values():
            for tool in tool_list:
                tools.append(tool)
        return tools

    def _run_child_agent_loop(
        self,
        task: str,
        context: str | None,
        turn_index: int,
        max_iterations: int = 5,
    ) -> str:
        """Run a simplified agent loop for the child agent with its tools."""
        from onyx.llm.message_types import (
            AssistantMessage,
            FunctionCall,
            SystemMessage,
            ToolCall,
            ToolMessage,
            UserMessageWithText,
        )

        child_tools = self._build_child_tools()
        tool_definitions = [tool.tool_definition() for tool in child_tools]
        tool_name_to_tool = {tool.name: tool for tool in child_tools}

        base_system_prompt = (
            self._child_persona.system_prompt or "You are a helpful assistant."
        )

        if child_tools:
            tool_names = [t.display_name for t in child_tools]
            tools_instruction = (
                f"\n\nYou have access to the following tools: {', '.join(tool_names)}. "
                "CRITICAL: You MUST use your tools to look up specific, accurate information before answering. "
                "Do NOT make up information, use placeholder text like '[specific value]', or provide generic responses. "
                "Always use your tools first to gather real data, then provide a response based on that data."
            )
            system_prompt = base_system_prompt + tools_instruction
        else:
            system_prompt = base_system_prompt

        full_prompt = f"Task: {task}"
        if context:
            full_prompt = f"Context: {context}\n\n{full_prompt}"

        if child_tools:
            full_prompt += (
                "\n\nREMINDER: Use your available tools to find real, specific information. "
                "Do not provide a response with placeholders or generic text."
            )

        messages: list = [
            SystemMessage(role="system", content=system_prompt),
            UserMessageWithText(role="user", content=full_prompt),
        ]

        logger.info(
            f"Running child agent '{self._child_persona.name}' with {len(child_tools)} tools: "
            f"{[t.name for t in child_tools]}"
        )

        final_response = ""
        collected_search_queries: list[str] = []
        collected_search_docs: list = []
        self._nested_agent_runs = []

        for iteration in range(max_iterations):
            logger.debug(f"Child agent iteration {iteration + 1}/{max_iterations}")

            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=AgentToolDelta(
                        agent_name=self._child_persona.name,
                        status_text=f"Thinking... (step {iteration + 1})",
                    ),
                )
            )

            if tool_definitions:
                current_tool_choice = "required" if iteration == 0 else "auto"
                logger.debug(
                    f"Child agent iteration {iteration + 1}: tool_choice={current_tool_choice}"
                )
                response = self._llm.invoke(
                    prompt=messages,
                    tools=tool_definitions,
                    tool_choice=current_tool_choice,
                )
            else:
                response = self._llm.invoke(prompt=messages)

            assistant_content = response.choice.message.content
            tool_calls = response.choice.message.tool_calls

            if tool_calls:
                tool_call_entries: list[ToolCall] = []
                for tc in tool_calls:
                    fn_name: str = tc.function.name if tc.function.name else ""
                    fn_args: str = (
                        tc.function.arguments if tc.function.arguments else "{}"
                    )
                    fn_call: FunctionCall = {"name": fn_name, "arguments": fn_args}
                    tc_entry: ToolCall = {
                        "id": tc.id,
                        "type": "function",
                        "function": fn_call,
                    }
                    tool_call_entries.append(tc_entry)

                assistant_msg: AssistantMessage = cast(
                    AssistantMessage,
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_call_entries,
                    },
                )
                messages.append(assistant_msg)

                for tool_call in tool_calls:
                    tool_name: str = (
                        tool_call.function.name if tool_call.function.name else ""
                    )
                    tool = tool_name_to_tool.get(tool_name)

                    if not tool:
                        logger.warning(
                            f"Tool {tool_name} not found for child agent. "
                            f"Available tools: {list(tool_name_to_tool.keys())}"
                        )
                        tool_result = f"Error: Tool {tool_name} not found"
                    else:
                        logger.info(
                            f"Child agent '{self._child_persona.name}' calling tool: {tool_name}"
                        )
                        self.emitter.emit(
                            Packet(
                                turn_index=turn_index,
                                obj=AgentToolDelta(
                                    agent_name=self._child_persona.name,
                                    status_text=f"Using {tool.display_name}...",
                                ),
                            )
                        )

                        try:
                            fn_arguments: str = (
                                tool_call.function.arguments
                                if tool_call.function.arguments
                                else "{}"
                            )
                            args = json.loads(fn_arguments)
                            logger.info(f"Tool {tool_name} called with args: {args}")

                            # Emit the tool start packet (normally done by tool_runner)
                            tool.emit_start(turn_index=turn_index)

                            tool_override_kwargs = self._get_tool_override_kwargs(
                                tool, task
                            )
                            tool_response = tool.run(
                                turn_index=turn_index,
                                override_kwargs=tool_override_kwargs,
                                **args,
                            )
                            tool_result = tool_response.llm_facing_response

                            # If this is a nested agent tool, capture its run (response + search data + deeper agents)
                            if isinstance(tool, AgentTool):
                                nested_queries = (
                                    getattr(tool, "_collected_search_queries", []) or []
                                )
                                nested_docs = (
                                    getattr(tool, "_collected_search_docs", []) or []
                                )
                                nested_doc_dicts = []
                                for doc in nested_docs:
                                    try:
                                        if hasattr(doc, "db_doc_id"):
                                            doc_dump = doc.model_dump()
                                            if doc_dump.get("db_doc_id") is None:
                                                doc_dump["db_doc_id"] = 0
                                        else:
                                            doc_dump = SavedSearchDoc.from_search_doc(
                                                doc, db_doc_id=0
                                            ).model_dump()
                                        nested_doc_dicts.append(doc_dump)
                                    except Exception:
                                        continue
                                nested_entry: dict = {
                                    "agent_name": tool._child_persona.name,
                                    "agent_id": tool._child_persona.id,
                                    "response": tool_result,
                                    "search_queries": nested_queries,
                                    "search_docs": nested_doc_dicts,
                                }
                                if getattr(tool, "_nested_agent_runs", None):
                                    nested_entry["nested_runs"] = (
                                        tool._nested_agent_runs
                                    )
                                self._nested_agent_runs.append(nested_entry)

                                # Bubble up nested agent search data
                                if nested_queries:
                                    existing_queries = set(collected_search_queries)
                                    for query in nested_queries:
                                        if query not in existing_queries:
                                            collected_search_queries.append(query)
                                            existing_queries.add(query)
                                if nested_docs:
                                    existing_doc_ids = {
                                        doc.document_id for doc in collected_search_docs
                                    }
                                    for doc in nested_docs:
                                        if doc.document_id not in existing_doc_ids:
                                            collected_search_docs.append(doc)
                                            existing_doc_ids.add(doc.document_id)

                            # Also collect from search tools directly
                            from onyx.tools.models import SearchDocsResponse

                            if isinstance(
                                tool_response.rich_response, SearchDocsResponse
                            ):
                                if tool_response.rich_response.search_docs:
                                    existing_doc_ids = {
                                        doc.document_id for doc in collected_search_docs
                                    }
                                    for doc in tool_response.rich_response.search_docs:
                                        if doc.document_id not in existing_doc_ids:
                                            collected_search_docs.append(doc)
                                            existing_doc_ids.add(doc.document_id)
                                # Extract queries from args if it's a search tool
                                if "queries" in args:
                                    queries = args["queries"]
                                    if isinstance(queries, list):
                                        existing_queries = set(collected_search_queries)
                                        for query in queries:
                                            if query not in existing_queries:
                                                collected_search_queries.append(query)
                                                existing_queries.add(query)

                            logger.info(
                                f"Tool {tool_name} returned {len(tool_result)} chars: "
                                f"{tool_result[:200]}..."
                            )
                        except Exception as e:
                            logger.exception(f"Error running tool {tool_name}")
                            tool_result = f"Error running tool: {str(e)}"

                    tool_msg: ToolMessage = {
                        "role": "tool",
                        "content": tool_result,
                        "tool_call_id": tool_call.id,
                    }
                    messages.append(tool_msg)

            else:
                if assistant_content:
                    final_response = assistant_content
                    logger.info(
                        f"Child agent '{self._child_persona.name}' final response "
                        f"({len(assistant_content)} chars): {assistant_content[:300]}..."
                    )
                    for chunk in [
                        assistant_content[i : i + 50]
                        for i in range(0, len(assistant_content), 50)
                    ]:
                        self.emitter.emit(
                            Packet(
                                turn_index=turn_index,
                                obj=AgentToolDelta(
                                    agent_name=self._child_persona.name,
                                    nested_content=chunk,
                                ),
                            )
                        )
                else:
                    logger.warning(
                        f"Child agent '{self._child_persona.name}' produced no response content"
                    )
                break

        if not final_response:
            logger.warning(
                f"Child agent '{self._child_persona.name}' loop ended without final response "
                f"after {max_iterations} iterations"
            )

        # Store collected data for persistence
        self._collected_search_queries = collected_search_queries
        self._collected_search_docs = collected_search_docs

        return final_response

    def run(
        self,
        turn_index: int,
        override_kwargs: AgentToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        task = llm_kwargs.get("task", "")
        context = llm_kwargs.get("context", "")

        current_depth = override_kwargs.current_depth if override_kwargs else 0
        parent_ids = override_kwargs.parent_agent_ids if override_kwargs else []

        if current_depth >= MAX_AGENT_RECURSION_DEPTH:
            error_msg = (
                f"Maximum agent recursion depth ({MAX_AGENT_RECURSION_DEPTH}) reached."
            )
            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=AgentToolFinal(
                        agent_name=self._child_persona.name,
                        summary=error_msg,
                        full_response=error_msg,
                    ),
                )
            )
            return ToolResponse(rich_response=None, llm_facing_response=error_msg)

        if self._child_persona.id in parent_ids:
            error_msg = f"Circular agent invocation detected. Agent '{self._child_persona.name}' is already in the call chain."
            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=AgentToolFinal(
                        agent_name=self._child_persona.name,
                        summary=error_msg,
                        full_response=error_msg,
                    ),
                )
            )
            return ToolResponse(rich_response=None, llm_facing_response=error_msg)

        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=AgentToolDelta(
                    agent_name=self._child_persona.name,
                    status_text=f"Processing task: {task[:100]}...",
                ),
            )
        )

        try:
            response_text = self._run_child_agent_loop(
                task=task,
                context=context,
                turn_index=turn_index,
            )

            if not response_text:
                response_text = "The agent did not produce a response."

            if self._config.max_tokens_from_child:
                max_chars = self._config.max_tokens_from_child * 4
                if len(response_text) > max_chars:
                    response_text = response_text[:max_chars] + "... [truncated]"

            summary = (
                response_text[:200] + "..."
                if len(response_text) > 200
                else response_text
            )

            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=AgentToolFinal(
                        agent_name=self._child_persona.name,
                        summary=summary,
                        full_response=response_text,
                    ),
                )
            )

            return ToolResponse(
                rich_response=None,
                llm_facing_response=f"Response from {self._child_persona.name}:\n{response_text}",
            )

        except Exception as e:
            logger.exception(f"Error invoking agent {self._child_persona.name}")
            error_msg = f"Error invoking agent: {str(e)}"
            self.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=AgentToolFinal(
                        agent_name=self._child_persona.name,
                        summary=error_msg,
                        full_response=error_msg,
                    ),
                )
            )
            return ToolResponse(rich_response=None, llm_facing_response=error_msg)
