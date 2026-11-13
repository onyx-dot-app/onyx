"""Real Anthropic calls reuse replayed evidence across separate chat agents."""

from uuid import uuid4

import pytest

from onyx.agents.models import AgentState, CompactionCheckpoint, PreparedStep, StepInput
from onyx.agents.tools import ToolInvocation
from onyx.chat.agent import ChatAgent
from onyx.file_store.models import ContextFileMetadata, ExtractedContextFiles
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.models import (
    Message,
    NamedToolChoice,
    ReasoningEffort,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tools.interface import Tool
from onyx.tools.models import CodeModeExposure, ToolContext
from tests.unit.onyx.agents.fakes import run_agent
from tests.utils.secret_names import TestSecret


class CatalogTool(Tool):
    """Return synthetic evidence without an external data dependency."""

    def __init__(self, evidence: str) -> None:
        self.evidence = evidence

    @property
    def id(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return "load_catalog"

    @property
    def description(self) -> str:
        return "Read the complete synthetic project catalog."

    @property
    def display_name(self) -> str:
        return "Catalog"

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        invocation.cancellation.check()
        return ToolResult(content=self.evidence)


@pytest.mark.secrets(TestSecret.ANTHROPIC_API_KEY)
def test_followup_reuses_cached_tool_evidence_after_agent_reconstruction(
    test_secrets: dict[TestSecret, str],
) -> None:
    model = LitellmLLM(
        api_key=test_secrets[TestSecret.ANTHROPIC_API_KEY],
        model_provider="anthropic",
        model_name="claude-haiku-4-5",
        max_input_tokens=200_000,
        temperature=0,
    )
    nonce = uuid4().hex
    evidence = "\n".join(
        f"Catalog record {index}: access code CODE-{index * 7919 + 12345}; warehouse north; status verified."
        for index in range(350)
    )
    expected = f"CODE-{137 * 7919 + 12345}"
    tool = CatalogTool(evidence)
    project_text = "This project's response prefix is HARBOR."
    files = ExtractedContextFiles(
        file_texts=[project_text],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=12,
        uncapped_token_count=12,
        file_metadata=[
            ContextFileMetadata(
                file_id="project-policy",
                filename="policy.txt",
                file_content=project_text,
            )
        ],
    )

    def agent(
        messages: list[Message],
        *,
        client: LitellmLLM = model,
        checkpoint: CompactionCheckpoint | None = None,
    ) -> ChatAgent:
        return ChatAgent(
            messages=messages,
            tools=[tool],
            custom_agent_prompt="Begin every final answer with the response prefix from the project policy followed by a colon. Keep answers brief.",
            base_system_prompt=f"You answer only from supplied evidence. Evaluation session {nonce}.",
            context_files=files,
            persona=None,
            user_memory_context=None,
            llm=client,
            token_counter=get_llm_token_counter(client),
            checkpoint=checkpoint,
            reasoning_effort=ReasoningEffort.OFF,
            include_citations=False,
            reminders_enabled=False,
        )

    first = agent(
        [
            UserMessage(
                content="Load the catalog. Then reply only READY, with the required prefix. Do not reveal any catalog values yet."
            )
        ],
    )
    prepare = first.prepare_step
    assert prepare is not None

    def load_catalog_first(step: StepInput) -> PreparedStep:
        prepared = prepare(step)
        if step.step.index == 0:
            return prepared.model_copy(
                update={
                    "options": prepared.options.model_copy(
                        update={"tool_choice": NamedToolChoice(name=tool.name)}
                    )
                }
            )
        return prepared

    # Make evidence setup deterministic; this test measures replay, not tool selection.
    first.prepare_step = load_catalog_first
    loaded = run_agent(first, max_steps=2)
    assert "HARBOR:" in loaded.output.text
    assert "READY" in loaded.output.text
    assert expected not in loaded.output.text
    assert any(
        isinstance(message, ToolResultMessage) for message in first.state.messages
    )

    # Rebuild a fresh agent from serialized canonical history, as a later request does.
    saved = first.state.model_dump_json()
    replay = AgentState.model_validate_json(saved)
    followup = UserMessage(
        content="From the catalog already loaded, what is the exact access code for record 137? Do not call a tool. Reply with the required prefix and code only. If the evidence is unavailable, reply with the required prefix and UNKNOWN."
    )
    retained = run_agent(agent([*replay.messages, followup]), max_steps=1)
    assert "HARBOR:" in retained.output.text
    assert expected in retained.output.text
    assert retained.output.usage is not None

    # Controlled comparison: replace old evidence to measure the previous policy.
    omitted = [
        message.model_copy(
            update={"content": "The earlier tool result is unavailable."}
        )
        if isinstance(message, ToolResultMessage)
        else message
        for message in replay.messages
    ]
    baseline = run_agent(agent([*omitted, followup]), max_steps=1)
    assert "HARBOR:" in baseline.output.text
    assert "UNKNOWN" in baseline.output.text
    assert baseline.output.usage is not None
    # Provider cache availability is diagnostic; replay correctness is asserted above.
    print(
        "Retained history usage:",
        retained.output.usage.model_dump(),
        "Omitted history usage:",
        baseline.output.usage.model_dump(),
    )

    # A smaller window must summarize history while keeping fixed instructions.
    small_model = LitellmLLM(
        api_key=test_secrets[TestSecret.ANTHROPIC_API_KEY],
        model_provider="anthropic",
        model_name="claude-haiku-4-5",
        max_input_tokens=6000,
        temperature=0,
    )
    compacted = agent(replay.messages, client=small_model)
    compacted_result = run_agent(
        compacted,
        messages=[
            UserMessage(
                content="Acknowledge with READY and the required prefix. Do not call tools."
            )
        ],
        max_steps=1,
    )
    assert "HARBOR:" in compacted_result.output.text
    assert "READY" in compacted_result.output.text
    assert compacted.state.checkpoint is not None
    assert compacted.state.checkpoint.summary
    restored = AgentState.model_validate_json(compacted.state.model_dump_json())
    resumed = agent(
        restored.messages, client=small_model, checkpoint=restored.checkpoint
    )
    resumed_result = run_agent(
        resumed,
        messages=[
            UserMessage(
                content="Acknowledge again with READY and the required prefix. Do not call tools."
            )
        ],
        max_steps=1,
    )
    assert "HARBOR:" in resumed_result.output.text
    assert "READY" in resumed_result.output.text
    assert resumed.state.checkpoint == restored.checkpoint
