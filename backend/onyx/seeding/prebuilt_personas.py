"""Prebuilt personas and prompts for Onyx.

This module defines the built-in personas with their embedded prompt configurations
using Pydantic models for strict typing and validation.
"""

from typing import Optional

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.models import StarterMessage


class PrebuiltPersona(BaseModel):
    """Model for a prebuilt persona with embedded prompt configuration."""

    # Persona identification
    id: Optional[int] = Field(default=None, description="Persona ID (optional)")
    name: str = Field(..., description="Name of the persona")
    description: str = Field(..., description="Description of the persona")

    # Prompt configuration (merged from Prompt table)
    system_prompt: str = Field(..., description="System prompt for the LLM")
    task_prompt: str = Field(..., description="Task prompt for the LLM")
    datetime_aware: bool = Field(
        default=True, description="Whether to include current date/time"
    )

    # Search and retrieval settings
    num_chunks: float = Field(default=25, description="Number of chunks to retrieve")
    chunks_above: int = Field(
        default=0, description="Additional chunks above matched chunk"
    )
    chunks_below: int = Field(
        default=0, description="Additional chunks below matched chunk"
    )
    llm_relevance_filter: bool = Field(
        default=False, description="Apply LLM relevance filtering"
    )
    llm_filter_extraction: bool = Field(
        default=True, description="Extract filters using LLM"
    )
    recency_bias: RecencyBiasSetting = Field(
        default=RecencyBiasSetting.AUTO, description="Document recency bias"
    )

    # UI configuration
    icon_shape: int = Field(default=0, description="Icon shape ID for UI")
    icon_color: str = Field(default="#6FB1FF", description="Icon color hex code")
    display_priority: int = Field(default=0, description="Display order priority")
    is_visible: bool = Field(
        default=True, description="Whether persona is visible in UI"
    )

    # Special flags
    is_default_persona: bool = Field(
        default=False, description="Whether this is a default persona"
    )
    builtin_persona: bool = Field(
        default=True, description="Whether this is a built-in persona"
    )
    image_generation: bool = Field(
        default=False, description="Whether persona supports image generation"
    )

    # Starter messages
    starter_messages: list[StarterMessage] = Field(
        default_factory=list, description="Starter messages for the persona"
    )

    # Document sets (names of document sets to attach)
    document_sets: list[str] = Field(
        default_factory=list, description="Document set names"
    )

    # LLM overrides
    llm_model_provider_override: Optional[str] = Field(
        default=None, description="Override LLM provider"
    )
    llm_model_version_override: Optional[str] = Field(
        default=None, description="Override LLM version"
    )


# Define the prebuilt personas
PREBUILT_PERSONAS = [
    # Unified Assistant (ID 0 - replacing Search persona)
    PrebuiltPersona(
        id=0,
        name="Assistant",
        description="Your AI assistant with search, web browsing, and image generation capabilities.",
        system_prompt=(
            "You are a helpful AI assistant that is constantly learning and improving.\n"
            "The current date is [[CURRENT_DATETIME]].\n\n"
            "You can process and comprehend vast amounts of text and utilize this knowledge to provide "
            "grounded, accurate, and concise answers to diverse queries.\n\n"
            "You have access to:\n"
            "1. Document search - to find information from connected sources\n"
            "2. Web search - to get up-to-date information from the internet\n"
            "3. Image generation - to create images based on descriptions\n\n"
            "You give concise responses to simple questions, but provide more thorough responses to "
            "complex and open-ended questions.\n\n"
            "You are happy to help with writing, analysis, question answering, math, coding and all sorts "
            "of other tasks. You use markdown where reasonable and also for coding.\n\n"
            "You always clearly communicate ANY UNCERTAINTY in your answer."
        ),
        task_prompt=(
            "Answer the user's query using the appropriate capabilities:\n"
            "- If documents are provided, use them to answer the question\n"
            "- If the query requires current information, use web search\n"
            "- If the query requires image generation, create the requested image\n"
            "- For general questions, use your knowledge and reasoning\n\n"
            "The documents may not all be relevant, ignore any documents that are not directly relevant "
            "to the most recent user query.\n\n"
            "I have not read or seen any of the documents and do not want to read them. "
            "Do not refer to them by Document number."
        ),
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
        image_generation=True,  # Enable image generation
        starter_messages=[
            # Search-related starter messages
            StarterMessage(
                name="Give me an overview of what's here",
                message="Sample some documents and tell me what you find.",
            ),
            StarterMessage(
                name="Find updates on a topic of interest",
                message=(
                    "Once I provide a topic, retrieve related documents and tell me when there was "
                    "last activity on the topic if available."
                ),
            ),
            # General assistant starter messages
            StarterMessage(
                name="Help me with coding",
                message='Write me a "Hello World" script in 5 random languages to show off the functionality.',
            ),
            StarterMessage(
                name="Draft a professional email",
                message=(
                    "Help me craft a professional email. Let's establish the context and the anticipated "
                    "outcomes of the email before proposing a draft."
                ),
            ),
            # Image generation starter messages
            StarterMessage(
                name="Create visuals for a presentation",
                message="Generate someone presenting a graph which clearly demonstrates an upwards trajectory.",
            ),
            StarterMessage(
                name="Visualize a product design",
                message=(
                    "I want to add a search bar to my Iphone app. Generate me generic examples of how "
                    "other apps implement this."
                ),
            ),
        ],
    ),
    # Paraphrase persona (ID 2) - Keep as non-default
    PrebuiltPersona(
        id=2,
        name="Paraphrase",
        description="Assistant that is heavily constrained and only provides exact quotes from Connected Sources.",
        system_prompt=(
            "Quote and cite relevant information from provided context based on the user query.\n"
            "The current date is [[CURRENT_DATETIME]].\n\n"
            "You only provide quotes that are EXACT substrings from provided documents!\n\n"
            "If there are no documents provided,\n"
            "simply tell the user that there are no documents to reference.\n\n"
            "You NEVER generate new text or phrases outside of the citation.\n"
            "DO NOT explain your responses, only provide the quotes and NOTHING ELSE."
        ),
        task_prompt=(
            "Provide EXACT quotes from the provided documents above. Do not generate any new text that is not\n"
            "directly from the documents."
        ),
        datetime_aware=True,
        num_chunks=10,
        llm_relevance_filter=True,
        llm_filter_extraction=True,
        recency_bias=RecencyBiasSetting.AUTO,
        icon_shape=45519,
        icon_color="#6FFF8D",
        display_priority=2,
        is_visible=False,
        is_default_persona=False,  # Changed to False - not a default
        starter_messages=[
            StarterMessage(
                name="Document Search",
                message=(
                    "Hi! Could you help me find information about our team structure and reporting lines "
                    "from our internal documents?"
                ),
            ),
            StarterMessage(
                name="Process Verification",
                message=(
                    "Hello! I need to understand our project approval process. Could you find the exact "
                    "steps from our documentation?"
                ),
            ),
            StarterMessage(
                name="Technical Documentation",
                message=(
                    "Hi there! I'm looking for information about our deployment procedures. Can you find "
                    "the specific steps from our technical guides?"
                ),
            ),
            StarterMessage(
                name="Policy Reference",
                message=(
                    "Hello! Could you help me find our official guidelines about client communication? "
                    "I need the exact wording from our documentation."
                ),
            ),
        ],
    ),
]


def get_prebuilt_personas() -> list[PrebuiltPersona]:
    """Get all prebuilt personas."""
    return PREBUILT_PERSONAS


def get_prebuilt_persona_by_id(persona_id: int) -> Optional[PrebuiltPersona]:
    """Get a specific prebuilt persona by ID."""
    for persona in PREBUILT_PERSONAS:
        if persona.id == persona_id:
            return persona
    return None


def get_prebuilt_persona_by_name(name: str) -> Optional[PrebuiltPersona]:
    """Get a specific prebuilt persona by name."""
    for persona in PREBUILT_PERSONAS:
        if persona.name == name:
            return persona
    return None
