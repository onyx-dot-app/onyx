"""The skills a chat agent can use: their catalog in its prompt, and the
skills a message picks."""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import accumulate
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.compaction import is_input_context
from onyx.chat.mention_models import (
    AcceptedPicks,
    Mention,
    PickedSkillMessage,
    RecordedSkillMention,
)
from onyx.llm.models import AssistantMessage, Message, UserMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.skill_prompts import (
    MENTIONED_SKILL_PROMPT,
    MENTIONED_SKILL_TRUNCATED_NOTE,
    SKILLS_CATALOG_PROMPT,
    SKILLS_OMITTED_LINE,
)
from onyx.skills.content import read_chat_skills_md
from onyx.skills.models import ChatSkill
from onyx.tools.constants import SKILLS_READ_TOOL_NAME

# Codex limits: the catalog's skill lines use at most 2% of the context
# window, at four UTF-8 bytes a token counted for each line with its newline;
# one description at most 1,024 characters; and a picked SKILL.md at most
# 8,000 bytes.
CATALOG_CONTEXT_PERCENT: Final = 2
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


def _catalog_line_tokens(line_bytes: int) -> int:
    """Codex's cost of a catalog line of this many bytes and its newline."""
    return (line_bytes + _BYTES_PER_TOKEN) // _BYTES_PER_TOKEN


def render_skills_catalog(
    skills: Sequence[ChatSkill], context_window_tokens: int
) -> str | None:
    """The catalog of skill names and descriptions, each skill's short
    description when it has one, fit to its budget as Codex fits it.

    Over budget, each skill in turn gets one more description character until
    no more fit; a description cut for the budget has no ellipsis. If names
    alone do not fit, the skills that fit are listed and a last line counts
    the rest. If not even that line fits, there is no catalog."""
    if not skills:
        return None
    budget = max(context_window_tokens * CATALOG_CONTEXT_PERCENT // 100, 1)
    descriptions = [skill.short_description or skill.description for skill in skills]
    capped = [truncate_catalog_description(text) for text in descriptions]
    # The bytes of each description cut to k characters. A cut before the
    # cap keeps no part of the cap's ellipsis.
    description_bytes = [
        [
            *accumulate(
                (len(char.encode()) for char in text[: len(cap) - 1]), initial=0
            ),
            len(cap.encode()),
        ]
        for text, cap in zip(descriptions, capped, strict=True)
    ]
    name_bytes = [len(f"- {skill.name}".encode()) for skill in skills]

    def line_tokens(index: int, chars: int) -> int:
        return _catalog_line_tokens(
            name_bytes[index]
            + (len(": ") + description_bytes[index][chars] if chars else 0)
        )

    def line(index: int, chars: int) -> str:
        if not chars:
            return f"- {skills[index].name}"
        text = (
            capped[index]
            if chars == len(capped[index])
            else descriptions[index][:chars]
        )
        return f"- {skills[index].name}: {text}"

    full = [len(cap) for cap in capped]
    if sum(map(line_tokens, range(len(skills)), full)) <= budget:
        return SKILLS_CATALOG_PROMPT.format(
            skills="\n".join(map(line, range(len(skills)), full))
        )
    remaining = budget - sum(line_tokens(index, 0) for index in range(len(skills)))
    if remaining >= 0:
        chars = [0] * len(skills)
        changed = True
        while changed:
            changed = False
            for index, count in enumerate(chars):
                if count == full[index]:
                    continue
                cost = line_tokens(index, count + 1) - line_tokens(index, count)
                if cost <= remaining:
                    chars[index] = count + 1
                    remaining -= cost
                    changed = True
        return SKILLS_CATALOG_PROMPT.format(
            skills="\n".join(map(line, range(len(skills)), chars))
        )

    kept: list[int] = []
    used = 0
    for index in range(len(skills)):
        if used + line_tokens(index, 0) <= budget:
            kept.append(index)
            used += line_tokens(index, 0)
    while True:
        count = len(skills) - len(kept)
        omitted_line = SKILLS_OMITTED_LINE.format(
            count=count, skills="skill" if count == 1 else "skills"
        )
        if used + _catalog_line_tokens(len(omitted_line.encode())) <= budget:
            break
        if not kept:
            return None
        used -= line_tokens(kept.pop(), 0)
    return SKILLS_CATALOG_PROMPT.format(
        skills="\n".join([*(line(index, 0) for index in kept), omitted_line])
    )


def accept_picked_skills(
    picks: Sequence[Sequence[Mention]],
    skills: Sequence[ChatSkill],
    user_id: UUID,
    db_session: Session,
    *,
    sandbox: bool,
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
    by_name = {skill.name: skill for skill in skills}
    readable = read_chat_skills_md(
        {
            by_name[mention.name]
            for mentions in picks
            for mention in mentions
            if mention.name in by_name
        },
        user_id,
        db_session,
        sandbox=sandbox,
    )
    # Stored counts use one tokenizer, as question counts do.
    tokenizer = get_tokenizer(None, None)
    accepted: list[AcceptedPicks] = []
    for mentions in picks:
        message = AcceptedPicks()
        for mention in dict.fromkeys(mentions):
            skill = by_name.get(mention.name)
            text = (
                readable.get((skill.version_id, skill.path))
                if skill is not None
                else None
            )
            if skill is None or text is None:
                continue
            version_id = skill.version_id
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


_PICKED_SKILL_NAME: Final = re.compile(r"\A<skill>\n<name>(.+?)</name>\n")


def used_skill_names(messages: Iterable[Message]) -> Counter[str]:
    """Count of `skills_read` calls and picks per skill name."""
    names: Counter[str] = Counter()
    for message in messages:
        if isinstance(message, AssistantMessage):
            for call in message.tool_calls:
                name = call.arguments.get("name")
                if call.name == SKILLS_READ_TOOL_NAME and isinstance(name, str):
                    names[name] += 1
        elif isinstance(message, UserMessage) and is_input_context(message):
            if match := _PICKED_SKILL_NAME.match(message.text):
                names[match.group(1)] += 1
    return names
