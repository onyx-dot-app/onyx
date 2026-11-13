from uuid import UUID, uuid4

from onyx.chat.chat_utils import convert_chat_history
from onyx.chat.mention_models import RecordedSkillMention, SkillMention
from onyx.chat.models import ChatHistoryMessage
from onyx.configs.constants import MessageType
from onyx.prompts.skill_prompts import SKILLS_OMITTED_LINE
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.skills.chat import (
    MAX_CATALOG_DESCRIPTION_CHARS,
    MAX_SKILL_PROMPT_BYTES,
    render_skills_catalog,
)
from onyx.skills.models import ChatSkill


def _skill(name: str, description: str = "Does a task.") -> ChatSkill:
    return ChatSkill(name=name, description=description, version_id=uuid4())


def _catalog_lines(catalog: str) -> list[str]:
    section = catalog.split("### Available skills\n", 1)[1].split("\n\n", 1)[0]
    return section.splitlines()


def test_catalog_lists_every_skill_within_budget() -> None:
    catalog = render_skills_catalog(
        [_skill("pdf-report", "Build a PDF\nreport."), _skill("triage", "")],
        200_000,
    )

    assert catalog is not None
    assert _catalog_lines(catalog) == ["- pdf-report: Build a PDF report.", "- triage"]


def test_catalog_is_empty_without_skills() -> None:
    assert render_skills_catalog([], 200_000) is None


def test_catalog_caps_one_description() -> None:
    catalog = render_skills_catalog([_skill("long", "x" * 5000)], 1_000_000)

    assert catalog is not None
    (line,) = _catalog_lines(catalog)
    assert line.endswith("...")
    assert len(line) == len("- long: ") + MAX_CATALOG_DESCRIPTION_CHARS


def test_catalog_shortens_long_descriptions_to_one_limit_over_budget() -> None:
    skills = [_skill(f"skill-{index}", "y" * 400) for index in range(10)]
    skills.append(_skill("short", "Fits."))
    # 2% of 20,000 tokens at four characters a token is 1,600 characters.
    catalog = render_skills_catalog(skills, 20_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    assert len(lines) == len(skills)
    total = len("\n".join(lines))
    assert total <= 1600
    cut = {len(line.split(": ", 1)[1]) for line in lines[:-1]}
    assert len(cut) == 1
    assert lines[-1] == "- short: Fits."
    # The largest limit is used: one more character for each cut description
    # would not fit.
    assert total + len(lines) - 1 > 1600


def test_catalog_omits_skills_when_names_do_not_fit() -> None:
    skills = [_skill(f"skill-number-{index}") for index in range(100)]
    catalog = render_skills_catalog(skills, 10_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    omitted = len(skills) - (len(lines) - 1)
    assert 1 < omitted < len(skills)
    assert lines[-1] == SKILLS_OMITTED_LINE.format(count=omitted, skills="skills")
    assert len("\n".join(lines)) <= 800
    assert lines[:-1] == [f"- {skill.name}" for skill in skills[: len(lines) - 1]]


def test_catalog_counts_one_omitted_skill_in_the_singular() -> None:
    # 240 characters: two names and the omitted line fit, three names do not.
    skills = [_skill("a" * 80), _skill("b" * 80), _skill("c" * 80)]
    catalog = render_skills_catalog(skills, 3_000)

    assert catalog is not None
    assert _catalog_lines(catalog)[-1] == SKILLS_OMITTED_LINE.format(
        count=1, skills="skill"
    )


def _mentioning_question(
    message_id: int, *skills: RecordedSkillMention
) -> ChatHistoryMessage:
    return ChatHistoryMessage(
        id=message_id,
        message_type=MessageType.USER,
        message="Use the skills.",
        token_count=3,
        files=[],
        is_clarification=False,
        mentions=list(skills),
        response_messages=[],
    )


def test_mentioned_skills_precede_their_question() -> None:
    triage = RecordedSkillMention(name="triage", version_id=uuid4())
    report = RecordedSkillMention(name="report", version_id=uuid4())

    history = convert_chat_history(
        [_mentioning_question(7, triage, report)],
        files=[],
        skill_instructions={triage.version_id: "Sort.", report.version_id: "Write."},
    )

    assert [message.id for message in history.messages] == [
        f"chat:7:skill:{triage.version_id}",
        f"chat:7:skill:{report.version_id}",
        "chat:7",
    ]
    assert history.messages[0].text == "<skill>\n<name>triage</name>\nSort.\n</skill>"


def test_mentioned_skill_is_cut_at_the_byte_limit_with_a_pointer() -> None:
    skill = RecordedSkillMention(name="triage", version_id=uuid4())
    # The byte limit falls inside a two-byte character, which is left out.
    kept = "a" + "é" * (MAX_SKILL_PROMPT_BYTES // 2 - 1)

    rendered = _rendered_skill(skill, {skill.version_id: kept + "é" * 10})

    assert f"<name>triage</name>\n{kept}\n\n[SKILL.md continues" in rendered
    assert f'name="triage" and start_char={len(kept)}' in rendered


def test_unreadable_mentioned_skill_says_it_is_unavailable() -> None:
    skill = RecordedSkillMention(name="triage", version_id=uuid4())

    rendered = _rendered_skill(skill, {})

    assert rendered.startswith("<skill>\n<name>triage</name>\n")
    assert "no longer available" in rendered


def _rendered_skill(skill: RecordedSkillMention, instructions: dict[UUID, str]) -> str:
    return (
        convert_chat_history(
            [_mentioning_question(1, skill)], files=[], skill_instructions=instructions
        )
        .messages[0]
        .text
    )


def test_send_request_accepts_a_recorded_mention_on_resend() -> None:
    request = SendMessageRequest.model_validate(
        {
            "message": "use @report",
            "mentions": [
                {"type": "skill", "name": "report", "version_id": str(uuid4())}
            ],
        }
    )

    assert request.mentions == [SkillMention(name="report")]
