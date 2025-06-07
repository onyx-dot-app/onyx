import os
from typing import Any
from typing import Optional

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
from pydantic import Field


class DeepResearchConfiguration(BaseModel):
    """The configuration for the deep research agent."""

    query_generator_model: str = Field(
        default="primary",
        metadata={
            "description": "The name of the language model to use for the agent's query generation."
        },
    )

    reflection_model: str = Field(
        default="primary",
        metadata={
            "description": "The name of the language model to use for the agent's reflection."
        },
    )

    answer_model: str = Field(
        default="primary",
        metadata={
            "description": "The name of the language model to use for the agent's answer."
        },
    )

    number_of_initial_queries: int = Field(
        default=3,
        metadata={"description": "The number of initial search queries to generate."},
    )

    max_research_loops: int = Field(
        default=2,
        metadata={"description": "The maximum number of research loops to perform."},
    )

    @classmethod
    def from_runnable_config(
        cls, config: Optional[RunnableConfig] = None
    ) -> "DeepResearchConfiguration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )

        # Get raw values from environment or config
        raw_values: dict[str, Any] = {
            name: os.environ.get(name.upper(), configurable.get(name))
            for name in cls.model_fields.keys()
        }

        # Filter out None values
        values = {k: v for k, v in raw_values.items() if v is not None}

        return cls(**values)


class DeepPlannerConfiguration(BaseModel):
    """The configuration for the deep planner agent."""

    max_steps: int = Field(
        default=10,
        metadata={"description": "The maximum number of steps to perform."},
    )
