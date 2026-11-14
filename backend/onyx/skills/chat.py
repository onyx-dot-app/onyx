"""The skills a chat agent can use: their catalog in its prompt, and the
skills a message picks."""

from bisect import bisect_right
from collections.abc import Sequence
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.mention_models import AcceptedSkillMention, Mention
from onyx.prompts.skill_prompts import (
    MENTIONED_SKILL_TRUNCATED_NOTE,
    SKILLS_CATALOG_PROMPT,
    SKILLS_OMITTED_LINE,
)
from onyx.skills.content import read_versions_instructions
from onyx.skills.models import ChatSkill

# Codex limits: the catalog uses at most 2% of the context window, at four
# UTF-8 bytes a token; one description at most 1,024 characters; and a picked
# SKILL.md at most 8,000 bytes.
CATALOG_CONTEXT_FRACTION: Final = 0.02
MAX_CATALOG_DESCRIPTION_CHARS: Final = 1024
MAX_SKILL_PROMPT_BYTES: Final = 8000
_BYTES_PER_TOKEN: Final = 4
_ELLIPSIS: Final = "..."


def truncate_skill_description(description: str, limit: int) -> str:
    """The description cut to `limit` characters with an ellipsis, or empty
    when the limit leaves no room past the ellipsis."""
    if len(description) <= limit:
        return description
    if limit <= len(_ELLIPSIS):
        return ""
    return description[: limit - len(_ELLIPSIS)] + _ELLIPSIS


def render_skills_catalog(
    skills: Sequence[ChatSkill], context_window_tokens: int
) -> str | None:
    """The catalog of skill names and descriptions, each skill's short
    description when it has one. Over budget, every description gets the same
    shorter limit; if names alone do not fit, the last skills are omitted and
    counted."""
    if not skills:
        return None
    budget = int(context_window_tokens * CATALOG_CONTEXT_FRACTION * _BYTES_PER_TOKEN)
    descriptions = [
        " ".join((skill.short_description or skill.description).split())
        for skill in skills
    ]

    def lines(limit: int) -> list[str]:
        return [
            f"- {skill.name}: {text}" if text else f"- {skill.name}"
            for skill, text in zip(
                skills,
                (truncate_skill_description(text, limit) for text in descriptions),
                strict=True,
            )
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
) -> list[list[AcceptedSkillMention]]:
    """Record the skills that each message picked, with the SKILL.md text that
    the message gives the model, from one read with the user's current access.

    A pick is recorded at the version the user runs, its text cut to
    `MAX_SKILL_PROMPT_BYTES` with a note where the rest begins. A skill that
    the user cannot use, or whose SKILL.md cannot be read, is left out, so the
    message does not apply it; a repeated pick counts once."""
    versions = {skill.name: skill.version_id for skill in skills}
    instructions = read_versions_instructions(
        {
            versions[mention.name]
            for mentions in picks
            for mention in mentions
            if mention.name in versions
        },
        user_id,
        db_session,
    )
    accepted: list[list[AcceptedSkillMention]] = []
    for mentions in picks:
        message_skills: list[AcceptedSkillMention] = []
        for mention in dict.fromkeys(mentions):
            version_id = versions.get(mention.name)
            text = instructions.get(version_id) if version_id is not None else None
            if version_id is None or text is None:
                continue
            if len(encoded := text.encode()) > MAX_SKILL_PROMPT_BYTES:
                # A cut inside a character leaves that character out.
                kept = encoded[:MAX_SKILL_PROMPT_BYTES].decode(errors="ignore")
                text = kept + MENTIONED_SKILL_TRUNCATED_NOTE.format(
                    name=mention.name, start_char=len(kept)
                )
            message_skills.append(
                AcceptedSkillMention(
                    name=mention.name, version_id=version_id, instructions=text
                )
            )
        accepted.append(message_skills)
    return accepted
