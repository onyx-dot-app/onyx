"""What a user tags in a chat message with `@`.

The request names what the user picked; the question records each pick the
turn resolved. Each kind is one member of the union on `type`; skills are the
only kind.

These models are used by requests, chat logic and DB columns, so they live in
a separate file to avoid circular imports.
"""

from collections.abc import Sequence
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.skills.models import ChatSkill, SkillName

MAX_MENTIONS_PER_MESSAGE: Final = 20


class SkillMention(BaseModel):
    """A custom skill the user picked for a message, by name. Extra fields are
    ignored, so a resend can pass back a recorded mention."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    name: SkillName


class RecordedSkillMention(BaseModel):
    """A skill the user picked for a question, at the version the user ran
    when the question was accepted."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    name: str
    version_id: UUID


Mention = Annotated[SkillMention, Field(discriminator="type")]
# The mentions of one message, as a request sends them and a queued message
# stores them.
Mentions = Annotated[list[Mention], Field(max_length=MAX_MENTIONS_PER_MESSAGE)]
RecordedMention = Annotated[RecordedSkillMention, Field(discriminator="type")]


class PickedMentions(BaseModel):
    """What a message sent into a running response picked, for its
    acceptance to resolve."""

    mentions: list[Mention]


def resolve_mentions(
    mentions: Sequence[Mention], skills: Sequence[ChatSkill]
) -> list[RecordedMention]:
    """Record each picked skill at the version the user runs. A skill the
    user cannot use is ignored, not rejected; a repeated pick counts once."""
    versions = {skill.name: skill.version_id for skill in skills}
    return [
        RecordedSkillMention(name=mention.name, version_id=versions[mention.name])
        for mention in dict.fromkeys(mentions)
        if mention.name in versions
    ]
