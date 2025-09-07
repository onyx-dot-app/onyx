"""Default personas for Onyx.

This module defines the default personas with their embedded prompt configurations.
It distinguishes between fields that are always updated on restart vs fields that
are only set on initial creation (and then controlled by admins).
"""

from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.models import Persona
from onyx.db.models import StarterMessage


class DefaultPersona(BaseModel):
    """Model for a default persona with embedded prompt configuration.

    Fields are categorized into:
    1. Always Updated: Core system fields that reset on every restart
    2. Admin Controlled: Set initially but then controlled by admin UI
    """

    # ============= ALWAYS UPDATED FIELDS =============
    # These fields are always reset to their configured values on restart

    # Core identification (always updated to ensure consistency)
    id: Optional[int] = Field(default=None, description="Persona ID (optional)")
    name: str = Field(..., description="Name of the persona - always updated")
    description: str = Field(..., description="Description - always updated")

    # System prompts (always updated to ensure latest system behavior)
    system_prompt: str = Field(..., description="System prompt - always updated")
    task_prompt: str = Field(..., description="Task prompt - always updated")
    datetime_aware: bool = Field(
        default=True, description="Datetime awareness - always updated"
    )

    # Core behavior flags (always updated for system consistency)
    builtin_persona: bool = Field(
        default=True, description="Built-in flag - always updated"
    )
    is_default_persona: bool = Field(
        default=False, description="Default persona flag - always updated"
    )

    # ============= ADMIN CONTROLLED FIELDS =============
    # These fields are set on initial creation but then controlled by admin

    # Search and retrieval settings (admin can tune these)
    num_chunks: float = Field(
        default=25, description="Chunks to retrieve - admin controlled"
    )
    chunks_above: int = Field(default=0, description="Chunks above - admin controlled")
    chunks_below: int = Field(default=0, description="Chunks below - admin controlled")
    llm_relevance_filter: bool = Field(
        default=False, description="LLM filtering - admin controlled"
    )
    llm_filter_extraction: bool = Field(
        default=True, description="Filter extraction - admin controlled"
    )
    recency_bias: RecencyBiasSetting = Field(
        default=RecencyBiasSetting.AUTO, description="Recency bias - admin controlled"
    )

    # UI configuration (admin controlled after initial setup)
    icon_shape: int = Field(default=0, description="Icon shape - admin controlled")
    icon_color: str = Field(
        default="#6FB1FF", description="Icon color - admin controlled"
    )
    display_priority: int = Field(
        default=0, description="Display priority - admin controlled"
    )
    is_visible: bool = Field(default=True, description="Visibility - admin controlled")

    # Capabilities (admin controlled)
    image_generation: bool = Field(
        default=False, description="Image generation capability - admin controlled"
    )

    # Starter messages (admin controlled)
    starter_messages: list[StarterMessage] = Field(
        default_factory=list, description="Starter messages - admin controlled"
    )

    # LLM overrides (admin controlled)
    llm_model_provider_override: Optional[str] = Field(
        default=None, description="LLM provider override - admin controlled"
    )
    llm_model_version_override: Optional[str] = Field(
        default=None, description="LLM version override - admin controlled"
    )


def apply_always_updated_fields(
    existing_persona: Persona, default_persona: "DefaultPersona"
) -> Persona:
    """Return the provided `existing_persona` with system fields refreshed from defaults.

    Only updates fields that must always track the default configuration. Admin-tuned
    fields (e.g. retrieval, UI, and overrides) are left unchanged.
    """
    existing_persona.name = default_persona.name
    existing_persona.description = default_persona.description
    existing_persona.system_prompt = default_persona.system_prompt
    existing_persona.task_prompt = default_persona.task_prompt
    existing_persona.datetime_aware = default_persona.datetime_aware
    existing_persona.builtin_persona = default_persona.builtin_persona
    existing_persona.is_default_persona = default_persona.is_default_persona
    return existing_persona


DEFAULT_SYSTEM_PROMPT = """
You are a helpful AI assistant that is constantly learning and improving.
The current date is [[CURRENT_DATETIME]].

You can process and comprehend vast amounts of text and utilize this knowledge to provide grounded, accurate, and \
concise answers to diverse queries.

You have access to:
1. Internal search - to find information from connected sources
2. Web search - to get up-to-date information from the internet

You give concise responses to simple questions, but provide more thorough responses to complex and open-ended questions.

You are happy to help with writing, analysis, question answering, math, coding and all sorts of other tasks. \
You use markdown where reasonable and also for coding.

You always clearly communicate ANY UNCERTAINTY in your answer.
""".strip()

# Unified Assistant (ID 0 - the main default assistant)
DEFAULT_PERSONA = DefaultPersona(
    id=0,
    name="Assistant",
    description="Your AI assistant with search, web browsing, and image generation capabilities.",
    system_prompt=DEFAULT_SYSTEM_PROMPT,
    task_prompt="",
    datetime_aware=True,
    num_chunks=25,  # Enable search
    llm_relevance_filter=False,
    llm_filter_extraction=True,
    recency_bias=RecencyBiasSetting.AUTO,
    icon_shape=23013,  # Keep the search icon
    icon_color="#6FB1FF",
    display_priority=0,
    is_visible=True,
    is_default_persona=True,
    image_generation=True,
    # no starter messages by default, let the admin configure if they want
    starter_messages=[],
)


def get_default_persona() -> DefaultPersona:
    """Get all default personas."""
    return DEFAULT_PERSONA
