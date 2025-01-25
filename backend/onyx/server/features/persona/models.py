from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.models import Persona
from onyx.db.models import PersonaLabel
from onyx.db.models import Prompt
from onyx.db.models import StarterMessage
from onyx.server.features.document_set.models import DocumentSet
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
    include_citations: bool
    datetime_aware: bool
    default_prompt: bool
    # Not including persona info, not needed

    @classmethod
    def from_model(cls, prompt: Prompt) -> "PromptSnapshot":
        if prompt.deleted:
            raise ValueError("Prompt has been deleted")

        return PromptSnapshot(
            id=prompt.id,
            name=prompt.name,
            description=prompt.description,
            system_prompt=prompt.system_prompt,
            task_prompt=prompt.task_prompt,
            include_citations=prompt.include_citations,
            datetime_aware=prompt.datetime_aware,
            default_prompt=prompt.default_prompt,
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
    system_prompt: str
    task_prompt: str
    datetime_aware: bool
    document_set_ids: list[int]
    num_chunks: float
    include_citations: bool
    is_public: bool
    recency_bias: RecencyBiasSetting
    prompt_ids: list[int]
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


class PersonaSnapshot(BaseModel):
    id: int
    owner: MinimalUserSnapshot | None
    name: str
    is_visible: bool
    is_public: bool
    display_priority: int | None
    description: str
    num_chunks: float | None
    llm_relevance_filter: bool
    llm_filter_extraction: bool
    llm_model_provider_override: str | None
    llm_model_version_override: str | None
    starter_messages: list[StarterMessage] | None
    builtin_persona: bool
    prompts: list[PromptSnapshot]
    tools: list[ToolSnapshot]
    document_sets: list[DocumentSet]
    users: list[MinimalUserSnapshot]
    groups: list[int]
    icon_color: str | None
    icon_shape: int | None
    uploaded_image_id: str | None = None
    is_default_persona: bool
    search_start_date: datetime | None = None
    labels: list["PersonaLabelSnapshot"] = []

    @classmethod
    def from_model(
        cls, persona: Persona, allow_deleted: bool = False
    ) -> "PersonaSnapshot":
        if persona.deleted:
            error_msg = f"Persona with ID {persona.id} has been deleted"
            if not allow_deleted:
                raise ValueError(error_msg)
            else:
                logger.warning(error_msg)

        return PersonaSnapshot(
            id=persona.id,
            name=persona.name,
            owner=(
                MinimalUserSnapshot(id=persona.user.id, email=persona.user.email)
                if persona.user
                else None
            ),
            is_visible=persona.is_visible,
            is_public=persona.is_public,
            display_priority=persona.display_priority,
            description=persona.description,
            num_chunks=persona.num_chunks,
            llm_relevance_filter=persona.llm_relevance_filter,
            llm_filter_extraction=persona.llm_filter_extraction,
            llm_model_provider_override=persona.llm_model_provider_override,
            llm_model_version_override=persona.llm_model_version_override,
            starter_messages=persona.starter_messages,
            builtin_persona=persona.builtin_persona,
            is_default_persona=persona.is_default_persona,
            prompts=[PromptSnapshot.from_model(prompt) for prompt in persona.prompts],
            tools=[ToolSnapshot.from_model(tool) for tool in persona.tools],
            document_sets=[
                DocumentSet.from_model(document_set_model)
                for document_set_model in persona.document_sets
            ],
            users=[
                MinimalUserSnapshot(id=user.id, email=user.email)
                for user in persona.users
            ],
            groups=[user_group.id for user_group in persona.groups],
            icon_color=persona.icon_color,
            icon_shape=persona.icon_shape,
            uploaded_image_id=persona.uploaded_image_id,
            search_start_date=persona.search_start_date,
            labels=[PersonaLabelSnapshot.from_model(label) for label in persona.labels],
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
