from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.models import Persona
from onyx.db.models import PersonaLabel
from onyx.db.models import StarterMessage
from onyx.server.features.document_set.models import DocumentSetSummary
from onyx.server.features.tool.models import ToolSnapshot
from onyx.server.models import MinimalUserSnapshot
from onyx.utils.logger import setup_logger


logger = setup_logger()


class PromptSnapshot(BaseModel):
    id: int
    name: str
    description: str
    system_prompt: str
    task_prompt: str
    datetime_aware: bool
    # Not including persona info, not needed

    @classmethod
    def from_model(cls, persona: Persona) -> "PromptSnapshot":
        """Create PromptSnapshot from persona's embedded prompt fields"""
        if persona.deleted:
            raise ValueError("Persona has been deleted")

        return PromptSnapshot(
            id=persona.id,
            name=persona.name,
            description=persona.description,
            system_prompt=persona.system_prompt or "",
            task_prompt=persona.task_prompt or "",
            datetime_aware=persona.datetime_aware,
        )


# More minimal request for generating a persona prompt
class GenerateStarterMessageRequest(BaseModel):
    name: str
    description: str
    instructions: str
    document_set_ids: list[int]
    generation_count: int


class PersonaUpsertRequest(BaseModel):
    name: str
    description: str
    document_set_ids: list[int]
    num_chunks: float
    is_public: bool
    recency_bias: RecencyBiasSetting
    llm_filter_extraction: bool
    llm_relevance_filter: bool
    llm_model_provider_override: str | None = None
    llm_model_version_override: str | None = None
    starter_messages: list[StarterMessage] | None = None
    # For Private Personas, who should be able to access these
    users: list[UUID] = Field(default_factory=list)
    groups: list[int] = Field(default_factory=list)
    # e.g. ID of SearchTool or ImageGenerationTool or <USER_DEFINED_TOOL>
    tool_ids: list[int]
    icon_color: str | None = None
    icon_shape: int | None = None
    remove_image: bool | None = None
    uploaded_image_id: str | None = None  # New field for uploaded image
    search_start_date: datetime | None = None
    label_ids: list[int] | None = None
    is_default_persona: bool = False
    display_priority: int | None = None
    # Accept string UUIDs from frontend
    user_file_ids: list[str] | None = None

    # prompt fields
    system_prompt: str
    task_prompt: str
    datetime_aware: bool


class MinimalPersonaSnapshot(BaseModel):
    """Minimal persona model optimized for ChatPage.tsx - only includes fields actually used"""

    # Core fields used by ChatPage
    id: int
    name: str
    description: str
    # Used for retrieval capability checking
    tools: list[ToolSnapshot]
    starter_messages: list[StarterMessage] | None

    llm_relevance_filter: bool
    llm_filter_extraction: bool

    # only show document sets in the UI that the assistant has access to
    document_sets: list[DocumentSetSummary]
    llm_model_version_override: str | None
    llm_model_provider_override: str | None

    uploaded_image_id: str | None
    icon_shape: int | None
    icon_color: str | None

    is_public: bool
    is_visible: bool
    display_priority: int | None
    is_default_persona: bool
    builtin_persona: bool

    # Used for filtering
    labels: list["PersonaLabelSnapshot"]

    # Used to display ownership
    owner: MinimalUserSnapshot | None

    @classmethod
    def from_model(cls, persona: Persona) -> "MinimalPersonaSnapshot":
        return MinimalPersonaSnapshot(
            # Core fields actually used by ChatPage
            id=persona.id,
            name=persona.name,
            description=persona.description,
            tools=[ToolSnapshot.from_model(tool) for tool in persona.tools],
            starter_messages=persona.starter_messages,
            llm_relevance_filter=persona.llm_relevance_filter,
            llm_filter_extraction=persona.llm_filter_extraction,
            document_sets=[
                DocumentSetSummary.from_model(document_set)
                for document_set in persona.document_sets
            ],
            llm_model_version_override=persona.llm_model_version_override,
            llm_model_provider_override=persona.llm_model_provider_override,
            uploaded_image_id=persona.uploaded_image_id,
            icon_shape=persona.icon_shape,
            icon_color=persona.icon_color,
            is_public=persona.is_public,
            is_visible=persona.is_visible,
            display_priority=persona.display_priority,
            is_default_persona=persona.is_default_persona,
            builtin_persona=persona.builtin_persona,
            labels=[PersonaLabelSnapshot.from_model(label) for label in persona.labels],
            owner=(
                MinimalUserSnapshot(id=persona.user.id, email=persona.user.email)
                if persona.user
                else None
            ),
        )


class PersonaSnapshot(BaseModel):
    id: int
    name: str
    description: str
    is_public: bool
    is_visible: bool
    icon_shape: int | None
    icon_color: str | None
    uploaded_image_id: str | None
    # Return string UUIDs to frontend for consistency
    user_file_ids: list[str]
    display_priority: int | None
    is_default_persona: bool
    builtin_persona: bool
    starter_messages: list[StarterMessage] | None
    llm_relevance_filter: bool
    llm_filter_extraction: bool
    tools: list[ToolSnapshot]
    labels: list["PersonaLabelSnapshot"]
    owner: MinimalUserSnapshot | None
    users: list[MinimalUserSnapshot]
    groups: list[int]
    document_sets: list[DocumentSetSummary]
    llm_model_provider_override: str | None
    llm_model_version_override: str | None
    num_chunks: float | None

    # Embedded prompt fields (no longer separate prompt_ids)
    system_prompt: str | None = None
    task_prompt: str | None = None
    datetime_aware: bool = True

    @classmethod
    def from_model(cls, persona: Persona) -> "PersonaSnapshot":
        return PersonaSnapshot(
            id=persona.id,
            name=persona.name,
            description=persona.description,
            is_public=persona.is_public,
            is_visible=persona.is_visible,
            icon_shape=persona.icon_shape,
            icon_color=persona.icon_color,
            uploaded_image_id=persona.uploaded_image_id,
            user_file_ids=[str(file.id) for file in persona.user_files],
            display_priority=persona.display_priority,
            is_default_persona=persona.is_default_persona,
            builtin_persona=persona.builtin_persona,
            starter_messages=persona.starter_messages,
            llm_relevance_filter=persona.llm_relevance_filter,
            llm_filter_extraction=persona.llm_filter_extraction,
            tools=[ToolSnapshot.from_model(tool) for tool in persona.tools],
            labels=[PersonaLabelSnapshot.from_model(label) for label in persona.labels],
            owner=(
                MinimalUserSnapshot(id=persona.user.id, email=persona.user.email)
                if persona.user
                else None
            ),
            users=[
                MinimalUserSnapshot(id=user.id, email=user.email)
                for user in persona.users
            ],
            groups=[user_group.id for user_group in persona.groups],
            document_sets=[
                DocumentSetSummary.from_model(document_set_model)
                for document_set_model in persona.document_sets
            ],
            llm_model_provider_override=persona.llm_model_provider_override,
            llm_model_version_override=persona.llm_model_version_override,
            num_chunks=persona.num_chunks,
            system_prompt=persona.system_prompt,
            task_prompt=persona.task_prompt,
            datetime_aware=persona.datetime_aware,
        )


# Model with full context on perona's internal settings
# This is used for flows which need to know all settings
class FullPersonaSnapshot(PersonaSnapshot):
    search_start_date: datetime | None = None
    llm_relevance_filter: bool = False
    llm_filter_extraction: bool = False

    @classmethod
    def from_model(
        cls, persona: Persona, allow_deleted: bool = False
    ) -> "FullPersonaSnapshot":
        if persona.deleted:
            error_msg = f"Persona with ID {persona.id} has been deleted"
            if not allow_deleted:
                raise ValueError(error_msg)
            else:
                logger.warning(error_msg)

        return FullPersonaSnapshot(
            id=persona.id,
            name=persona.name,
            description=persona.description,
            is_public=persona.is_public,
            is_visible=persona.is_visible,
            icon_shape=persona.icon_shape,
            icon_color=persona.icon_color,
            uploaded_image_id=persona.uploaded_image_id,
            user_file_ids=[str(file.id) for file in persona.user_files],
            display_priority=persona.display_priority,
            is_default_persona=persona.is_default_persona,
            builtin_persona=persona.builtin_persona,
            starter_messages=persona.starter_messages,
            users=[
                MinimalUserSnapshot(id=user.id, email=user.email)
                for user in persona.users
            ],
            groups=[user_group.id for user_group in persona.groups],
            tools=[ToolSnapshot.from_model(tool) for tool in persona.tools],
            labels=[PersonaLabelSnapshot.from_model(label) for label in persona.labels],
            owner=(
                MinimalUserSnapshot(id=persona.user.id, email=persona.user.email)
                if persona.user
                else None
            ),
            document_sets=[
                DocumentSetSummary.from_model(document_set_model)
                for document_set_model in persona.document_sets
            ],
            num_chunks=persona.num_chunks,
            search_start_date=persona.search_start_date,
            llm_relevance_filter=persona.llm_relevance_filter,
            llm_filter_extraction=persona.llm_filter_extraction,
            llm_model_provider_override=persona.llm_model_provider_override,
            llm_model_version_override=persona.llm_model_version_override,
            system_prompt=persona.system_prompt,
            task_prompt=persona.task_prompt,
            datetime_aware=persona.datetime_aware,
        )


class PromptTemplateResponse(BaseModel):
    final_prompt_template: str


class PersonaSharedNotificationData(BaseModel):
    persona_id: int


class ImageGenerationToolStatus(BaseModel):
    is_available: bool


class PersonaLabelCreate(BaseModel):
    name: str


class PersonaLabelResponse(BaseModel):
    id: int
    name: str

    @classmethod
    def from_model(cls, category: PersonaLabel) -> "PersonaLabelResponse":
        return PersonaLabelResponse(
            id=category.id,
            name=category.name,
        )


class PersonaLabelSnapshot(BaseModel):
    id: int
    name: str

    @classmethod
    def from_model(cls, label: PersonaLabel) -> "PersonaLabelSnapshot":
        return PersonaLabelSnapshot(
            id=label.id,
            name=label.name,
        )
