"""What a user tags in a chat message with `@`.

The request names what the user picked; the question records each pick the
turn resolved. Each kind is one member of the union on `type`; skills are the
only kind.

These models are used by requests, chat logic and DB columns, so they live in
a separate file to avoid circular imports.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SkillMention(BaseModel):
    """A custom skill the user picked for a message, by name. Extra fields are
    ignored, so a resend can pass back a recorded mention."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    name: str


class RecordedSkillMention(BaseModel):
    """A skill the user picked for a question, at the version the user ran
    when the question was accepted."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    name: str
    version_id: UUID


Mention = Annotated[SkillMention, Field(discriminator="type")]
RecordedMention = Annotated[RecordedSkillMention, Field(discriminator="type")]
