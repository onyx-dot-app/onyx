"""The catalog of the skills a chat agent can use, in its prompt."""

from bisect import bisect_right
from collections.abc import Sequence
from typing import Final

from onyx.prompts.skill_prompts import SKILLS_CATALOG_PROMPT, SKILLS_OMITTED_LINE
from onyx.skills.models import ChatSkill

# Codex limits: the catalog uses at most 2% of the context window, one
# description at most 1,024 characters, and a mentioned SKILL.md at most 8,000
# bytes.
CATALOG_CONTEXT_FRACTION: Final = 0.02
MAX_CATALOG_DESCRIPTION_CHARS: Final = 1024
MAX_SKILL_PROMPT_BYTES: Final = 8000
_CHARS_PER_TOKEN: Final = 4
_ELLIPSIS: Final = "..."


def render_skills_catalog(
    skills: Sequence[ChatSkill], context_window_tokens: int
) -> str | None:
    """The catalog of skill names and descriptions. Over budget, every
    description gets the same shorter limit; if names alone do not fit, the
    last skills are omitted and counted."""
    if not skills:
        return None
    budget = int(context_window_tokens * CATALOG_CONTEXT_FRACTION * _CHARS_PER_TOKEN)
    descriptions = [" ".join(skill.description.split()) for skill in skills]

    def lines(limit: int) -> list[str]:
        # A description over the limit is cut to it, or left out when the
        # limit leaves no room past the ellipsis.
        return [
            f"- {skill.name}: {text}" if text else f"- {skill.name}"
            for skill, text in zip(
                skills,
                (
                    text
                    if len(text) <= limit
                    else text[: limit - len(_ELLIPSIS)] + _ELLIPSIS
                    if limit > len(_ELLIPSIS)
                    else ""
                    for text in descriptions
                ),
                strict=True,
            )
        ]

    limit = (
        bisect_right(
            range(MAX_CATALOG_DESCRIPTION_CHARS + 1),
            budget,
            key=lambda limit: len("\n".join(lines(limit))),
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
            key=lambda kept: len("\n".join(with_omitted_line(kept))),
        )
        - 1,
        0,
    )
    return SKILLS_CATALOG_PROMPT.format(skills="\n".join(with_omitted_line(kept)))
