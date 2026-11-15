"""The skills a chat agent can use: their catalog in its prompt, and the
skills a message picks."""

from bisect import bisect_right
from collections.abc import Sequence
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.mention_models import (
    AcceptedPicks,
    Mention,
    PickedSkillMessage,
    RecordedSkillMention,
)
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.skill_prompts import (
    MENTIONED_SKILL_PROMPT,
    MENTIONED_SKILL_TRUNCATED_NOTE,
    SKILLS_CATALOG_PROMPT,
    SKILLS_OMITTED_LINE,
)
from onyx.skills.content import read_versions_skill_md
from onyx.skills.models import ChatSkill

# Codex limits: the catalog uses at most 2% of the context window, at four
# UTF-8 bytes a token; one description at most 1,024 characters; and a picked
# SKILL.md at most 8,000 bytes.
CATALOG_CONTEXT_FRACTION: Final = 0.02
MAX_CATALOG_DESCRIPTION_CHARS: Final = 1024
MAX_SKILL_PROMPT_BYTES: Final = 8000
_BYTES_PER_TOKEN: Final = 4
_ELLIPSIS: Final = "..."


def truncate_catalog_description(description: str) -> str:
    """The description cut to the catalog's limit, with an ellipsis where it
    is cut."""
    if len(description) <= MAX_CATALOG_DESCRIPTION_CHARS:
        return description
    return description[: MAX_CATALOG_DESCRIPTION_CHARS - len(_ELLIPSIS)] + _ELLIPSIS


def render_skills_catalog(
    skills: Sequence[ChatSkill], context_window_tokens: int
) -> str | None:
    """The catalog of skill names and descriptions, each skill's short
    description when it has one. Over budget, every description is cut to the
    same shorter limit, without an ellipsis; if names alone do not fit, the
    last skills are omitted and counted."""
    if not skills:
        return None
    budget = int(context_window_tokens * CATALOG_CONTEXT_FRACTION * _BYTES_PER_TOKEN)
    descriptions = [
        truncate_catalog_description(skill.short_description or skill.description)
        for skill in skills
    ]

    def lines(limit: int) -> list[str]:
        return [
            f"- {skill.name}: {text[:limit]}" if text[:limit] else f"- {skill.name}"
            for skill, text in zip(skills, descriptions, strict=True)
        ]

    limit = (
        bisect_right(
            range(MAX_CATALOG_DESCRIPTION_CHARS + 1),
            budget,
            key=lambda limit: len("\n".join(lines(limit)).encode()),
        )
        - 1
    )
    if limit >= 0:
        return SKILLS_CATALOG_PROMPT.format(skills="\n".join(lines(limit)))

    names = lines(0)

    def with_omitted_line(kept: int) -> list[str]:
        count = len(skills) - kept
        return [
            *names[:kept],
            SKILLS_OMITTED_LINE.format(
                count=count, skills="skill" if count == 1 else "skills"
            ),
        ]

    kept = max(
        bisect_right(
            range(len(skills)),
            budget,
            key=lambda kept: len("\n".join(with_omitted_line(kept)).encode()),
        )
        - 1,
        0,
    )
    return SKILLS_CATALOG_PROMPT.format(skills="\n".join(with_omitted_line(kept)))


def accept_picked_skills(
    picks: Sequence[Sequence[Mention]],
    skills: Sequence[ChatSkill],
    user_id: UUID,
    db_session: Session,
) -> list[AcceptedPicks]:
    """Resolve the skills that each message picked, from one read with the
    user's current access.

    `skills` is the list the message is accepted against: the turn's, or the
    running response's. A pick is recorded at that version, with the
    `<skill>` message it gives the model: the whole SKILL.md, cut to
    `MAX_SKILL_PROMPT_BYTES` with a note where the rest begins, and its token
    count. A skill that the user cannot use, or whose SKILL.md cannot be
    read, is left out, so the message does not apply it; a repeated pick
    counts once."""
    versions = {skill.name: skill.version_id for skill in skills}
    readable = read_versions_skill_md(
        {
            versions[mention.name]
            for mentions in picks
            for mention in mentions
            if mention.name in versions
        },
        user_id,
        db_session,
    )
    # Stored counts use one tokenizer, as question counts do.
    tokenizer = get_tokenizer(None, None)
    accepted: list[AcceptedPicks] = []
    for mentions in picks:
        message = AcceptedPicks()
        for mention in dict.fromkeys(mentions):
            version_id = versions.get(mention.name)
            text = readable.get(version_id) if version_id is not None else None
            if version_id is None or text is None:
                continue
            if len(encoded := text.encode()) > MAX_SKILL_PROMPT_BYTES:
                # A cut inside a character leaves that character out.
                kept = encoded[:MAX_SKILL_PROMPT_BYTES].decode(errors="ignore")
                text = kept + MENTIONED_SKILL_TRUNCATED_NOTE.format(
                    name=mention.name, start_char=len(kept)
                )
            content = MENTIONED_SKILL_PROMPT.format(
                name=mention.name, instructions=text
            )
            message.mentions.append(
                RecordedSkillMention(name=mention.name, version_id=version_id)
            )
            message.skill_messages.append(
                PickedSkillMessage(
                    version_id=version_id,
                    content=content,
                    token_count=len(tokenizer.encode(content)),
                )
            )
        accepted.append(message)
    return accepted
