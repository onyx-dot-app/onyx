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
    # Search persona (ID 0 - required for OnyxBot)
    PrebuiltPersona(
        id=0,
        name="Search",
        description="Assistant with access to documents and knowledge from Connected Sources.",
        system_prompt=(
            "You are a question answering system that is constantly learning and improving.\n"
            "The current date is [[CURRENT_DATETIME]].\n\n"
            "You can process and comprehend vast amounts of text and utilize this knowledge to provide\n"
            "grounded, accurate, and concise answers to diverse queries.\n\n"
            "You always clearly communicate ANY UNCERTAINTY in your answer."
        ),
        task_prompt=(
            "Answer my query based on the documents provided.\n"
            "The documents may not all be relevant, ignore any documents that are not directly relevant\n"
            "to the most recent user query.\n\n"
            "I have not read or seen any of the documents and do not want to read them. "
            "Do not refer to them by Document number.\n\n"
            "If there are no relevant documents, refer to the chat history and your internal knowledge."
        ),
        datetime_aware=True,
        num_chunks=25,
        llm_relevance_filter=False,
        llm_filter_extraction=True,
        recency_bias=RecencyBiasSetting.AUTO,
        icon_shape=23013,
        icon_color="#6FB1FF",
        display_priority=0,
        is_visible=True,
        is_default_persona=True,
        starter_messages=[
            StarterMessage(
                name="Give me an overview of what's here",
                message="Sample some documents and tell me what you find.",
            ),
            StarterMessage(
                name="Use AI to solve a work related problem",
                message="Ask me what problem I would like to solve, then search the knowledge base to help me find a solution.",
            ),
            StarterMessage(
                name="Find updates on a topic of interest",
                message=(
                    "Once I provide a topic, retrieve related documents and tell me when there was "
                    "last activity on the topic if available."
                ),
            ),
            StarterMessage(
                name="Surface contradictions",
                message=(
                    "Have me choose a subject. Once I have provided it, check against the knowledge base "
                    "and point out any inconsistencies. For all your following responses, focus on "
                    "identifying contradictions."
                ),
            ),
        ],
    ),
    # General persona (ID 1)
    PrebuiltPersona(
        id=1,
        name="General",
        description="Assistant with no search functionalities. Chat directly with the Large Language Model.",
        system_prompt=(
            "You are a helpful AI assistant. The current date is [[CURRENT_DATETIME]]\n\n\n"
            "You give concise responses to very simple questions, but provide more thorough responses to\n"
            "more complex and open-ended questions.\n\n\n"
            "You are happy to help with writing, analysis, question answering, math, coding and all sorts\n"
            "of other tasks. You use markdown where reasonable and also for coding."
        ),
        task_prompt="",
        datetime_aware=True,
        num_chunks=0,  # No search/retrieval
        llm_relevance_filter=True,
        llm_filter_extraction=True,
        recency_bias=RecencyBiasSetting.AUTO,
        icon_shape=50910,
        icon_color="#FF6F6F",
        display_priority=1,
        is_visible=True,
        is_default_persona=True,
        starter_messages=[
            StarterMessage(
                name="Summarize a document",
                message=(
                    "If I have provided a document please summarize it for me. If not, please ask me to "
                    "upload a document either by dragging it into the input bar or clicking the +file icon."
                ),
            ),
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
            StarterMessage(
                name="Learn something new",
                message="What is the difference between a Gantt chart, a Burndown chart and a Kanban board?",
            ),
        ],
    ),
    # Paraphrase persona (ID 2)
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
        is_default_persona=True,
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
    # Art/Image Generation persona (ID 3)
    PrebuiltPersona(
        id=3,
        name="Art",
        description="Assistant for generating images based on descriptions.",
        system_prompt=(
            "You are an AI image generation assistant. Your role is to create high-quality images based on user descriptions.\n\n"
            "For appropriate requests, you will generate an image that matches the user's requirements.\n"
            "For inappropriate or unsafe requests, you will politely decline and explain why the request cannot be fulfilled.\n\n"
            "You aim to be helpful while maintaining appropriate content standards."
        ),
        task_prompt=(
            "Based on the user's description, create a high-quality image that accurately reflects their request. \n"
            "Pay close attention to the specified details, styles, and desired elements.\n\n"
            "If the request is not appropriate or cannot be fulfilled, explain why and suggest alternatives."
        ),
        datetime_aware=True,
        num_chunks=0,  # No search/retrieval
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias=RecencyBiasSetting.NO_DECAY,
        icon_shape=234124,
        icon_color="#9B59B6",
        image_generation=True,
        display_priority=3,
        is_visible=True,
        is_default_persona=True,
        starter_messages=[
            StarterMessage(
                name="Create visuals for a presentation",
                message="Generate someone presenting a graph which clearly demonstrates an upwards trajectory.",
            ),
            StarterMessage(
                name="Find inspiration for a marketing campaign",
                message="Generate an image of two happy individuals sipping on a soda drink in a glass bottle.",
            ),
            StarterMessage(
                name="Visualize a product design",
                message=(
                    "I want to add a search bar to my Iphone app. Generate me generic examples of how "
                    "other apps implement this."
                ),
            ),
            StarterMessage(
                name="Generate a humorous image response",
                message="My teammate just made a silly mistake and I want to respond with a facepalm. Can you generate me one?",
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
