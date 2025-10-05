import asyncio
import os

from agents import ModelSettings
from agents import run_demo_loop
from agents.agent import Agent
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from agents.extensions.models.litellm_model import LitellmModel
from pydantic import BaseModel

from onyx.agents.agent_search.dr.dr_prompt_builder import (
    get_dr_prompt_orchestration_templates,
)
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import DRPromptPurpose


def construct_simple_agent() -> Agent:
    litellm_model = LitellmModel(
        model="gpt-4.1",
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    return Agent(
        name="Assistant",
        instructions="""
        You are a helpful assistant that can search the web, fetch content from URLs,
        and search internal databases.
        """,
        model=litellm_model,
        tools=[],
        model_settings=ModelSettings(
            temperature=0.0,
            include_usage=True,  # Track usage metrics
        ),
    )


class ClarificationOutput(BaseModel):
    clarification_question: str
    clarification_needed: bool


def construct_dr_agent() -> Agent:
    simple_agent = construct_simple_agent()
    litellm_model = LitellmModel(
        model="gpt-4.1",
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    base_clarification_prompt = get_dr_prompt_orchestration_templates(
        DRPromptPurpose.CLARIFICATION,
        research_type=ResearchType.DEEP,
        entity_types_string=None,
        relationship_types_string=None,
        available_tools={},
    )
    clarification_prompt = base_clarification_prompt.build(
        question="",
        chat_history_string="",
    )
    clarifier_prompt = prompt_with_handoff_instructions(clarification_prompt)
    clarifier_agent = Agent(
        name="Clarifier",
        instructions=clarifier_prompt,
        model=litellm_model,
        tools=[],
        output_type=ClarificationOutput,
        handoffs=[simple_agent],
        model_settings=ModelSettings(tool_choice="required"),
    )
    return clarifier_agent


async def main() -> None:
    agent = construct_dr_agent()
    await run_demo_loop(agent)


if __name__ == "__main__":
    asyncio.run(main())
