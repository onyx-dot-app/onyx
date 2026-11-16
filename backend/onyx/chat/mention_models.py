"""What a user tags in a chat message with `@`.

The request names what the user picked; the accepted message records each pick
at the version the user ran, and keeps the `<skill>` message it gave the model
apart from the record. Each kind is one member of the union on `type`;
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


class PickedSkillMessage(BaseModel):
    """The `<skill>` message that a pick of a skill version gave the model:
    the version's SKILL.md, cut to the prompt limit. A message keeps these
    apart from its records, so that only the history the model gets loads
    them."""

    model_config = ConfigDict(frozen=True)

    version_id: UUID
    content: str
    # Counted once, when the pick is accepted.
    token_count: int


Mention = Annotated[SkillMention, Field(discriminator="type")]
# The mentions of one message, as a request sends them and a queued message
# stores them.
Mentions = Annotated[list[Mention], Field(max_length=MAX_MENTIONS_PER_MESSAGE)]
RecordedMention = Annotated[RecordedSkillMention, Field(discriminator="type")]


class AcceptedPicks(BaseModel):
    """What one message picked, as its acceptance resolved it: the records,
    and the `<skill>` message of each."""

    mentions: list[RecordedMention] = Field(default_factory=list)
    skill_messages: list[PickedSkillMessage] = Field(default_factory=list)


class PickedMentions(BaseModel):
    """What a message sent into a running response picked, for its
    acceptance to resolve."""

    mentions: list[Mention]
