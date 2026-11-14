"""What a user tags in a chat message with `@`.

The request names what the user picked; the accepted message records each pick
with what it gave the model. Each kind is one member of the union on `type`;
skills are the only kind.

These models are used by requests, chat logic and DB columns, so they live in
a separate file to avoid circular imports.
"""

from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.skills.models import SkillName

MAX_MENTIONS_PER_MESSAGE: Final = 20


class SkillMention(BaseModel):
    """A custom skill the user picked for a message, by name. Extra fields are
    ignored, so a resend can pass back a recorded mention."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    name: SkillName


class RecordedSkillMention(BaseModel):
    """A skill the user picked for a message, at the version the user ran
    when the message was accepted. Clients see this record."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    name: str
    version_id: UUID


class AcceptedSkillMention(RecordedSkillMention):
    """A recorded pick with the SKILL.md text that the message gave the model.
    A field typed as the record serializes without the text."""

    # Cut to the prompt limit, with a note where the rest begins. None where
    # the row keeps no conversation content.
    instructions: str | None = None


Mention = Annotated[SkillMention, Field(discriminator="type")]
# The mentions of one message, as a request sends them and a queued message
# stores them.
Mentions = Annotated[list[Mention], Field(max_length=MAX_MENTIONS_PER_MESSAGE)]
RecordedMention = Annotated[RecordedSkillMention, Field(discriminator="type")]
AcceptedMention = Annotated[AcceptedSkillMention, Field(discriminator="type")]


class PickedMentions(BaseModel):
    """What a message sent into a running response picked, for its
    acceptance to resolve."""

    mentions: list[Mention]
