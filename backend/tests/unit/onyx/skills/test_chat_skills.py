from unittest.mock import Mock, patch
from uuid import uuid4

from onyx.agents.tools import ToolInvocation
from onyx.chat.mention_models import SkillMention
from onyx.llm.cancellation import CancellationSignal
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.prompts.skill_prompts import SKILLS_OMITTED_LINE
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.skills.chat import (
    MAX_CATALOG_DESCRIPTION_CHARS,
    MAX_SKILL_PROMPT_BYTES,
    accept_picked_skills,
    render_skills_catalog,
)
from onyx.skills.models import ChatSkill
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.skills.skill_tools import SkillsListTool


def _skill(
    name: str, description: str = "Does a task.", short_description: str | None = None
) -> ChatSkill:
    return ChatSkill(
        name=name,
        description=description,
        short_description=short_description,
        version_id=uuid4(),
    )


def _catalog_lines(catalog: str) -> list[str]:
    section = catalog.split("### Available skills\n", 1)[1]
    return section.split("\n### How to use skills", 1)[0].splitlines()


def test_catalog_lists_every_skill_within_budget() -> None:
    catalog = render_skills_catalog(
        [
            _skill("pdf-report", "Build a PDF\nreport."),
            _skill("triage", ""),
            _skill("notes", "Write long release notes.", short_description="Notes."),
        ],
        200_000,
    )

    assert catalog is not None
    # A short description wins.
    assert _catalog_lines(catalog) == [
        "- pdf-report: Build a PDF report.",
        "- triage",
        "- notes: Notes.",
    ]


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
    # 2% of 20,000 tokens at four bytes a token is 1,600 bytes.
    catalog = render_skills_catalog(skills, 20_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    assert len(lines) == len(skills)
    total = len("\n".join(lines))
    assert total <= 1600
    cut = {len(line.split(": ", 1)[1]) for line in lines[:-1]}
    assert len(cut) == 1
    assert lines[-1] == "- short: Fits."
    # A description cut for the budget has no ellipsis.
    assert not any(line.endswith("...") for line in lines)
    # The largest limit is used: one more character for each cut description
    # would not fit.
    assert total + len(lines) - 1 > 1600


def test_catalog_budget_counts_utf8_bytes() -> None:
    # Two bytes a character: the character count fits the budget, the byte
    # count does not.
    skills = [_skill(f"skill-{index}", "é" * 100) for index in range(10)]

    catalog = render_skills_catalog(skills, 20_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    assert len("\n".join(lines).encode()) <= 1600
    assert all(
        line.endswith("é") and len(line) < len("- skill-0: ") + 100 for line in lines
    )


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
    # 240 bytes: two names and the omitted line fit, three names do not.
    skills = [_skill("a" * 80), _skill("b" * 80), _skill("c" * 80)]
    catalog = render_skills_catalog(skills, 3_000)

    assert catalog is not None
    assert _catalog_lines(catalog)[-1] == SKILLS_OMITTED_LINE.format(
        count=1, skills="skill"
    )


def test_skills_list_shows_the_full_description_capped() -> None:
    skills = [
        _skill("notes", "Write release notes.", short_description="Notes."),
        _skill("long", "z" * 2000),
    ]

    result = SkillsListTool(skills)._run(
        ToolInvocation(
            call_id="list",
            arguments={},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )

    notes, long = result.content.splitlines()
    assert notes == "- notes: Write release notes."
    assert long == "- long: " + "z" * (MAX_CATALOG_DESCRIPTION_CHARS - 3) + "..."


def test_chat_skill_descriptions_are_one_line() -> None:
    skill = ChatSkill(
        name="notes",
        description="Write\n  release   notes.",
        short_description=" \n ",
        version_id=uuid4(),
    )

    # A blank short description is none, so the description is used.
    assert (skill.description, skill.short_description) == (
        "Write release notes.",
        None,
    )


def test_picked_skills_are_recorded_with_their_skill_messages_from_one_read() -> None:
    triage = _skill("triage")
    report = _skill("report")
    unreadable = _skill("unreadable")
    # The whole SKILL.md is cut; the byte limit falls inside a two-byte
    # character, which is left out.
    kept = "---\nname: report\n---\n" + "é" * (MAX_SKILL_PROMPT_BYTES // 2 - 11)
    assert len(kept.encode()) == MAX_SKILL_PROMPT_BYTES - 1
    read = Mock(
        return_value={triage.version_id: "Sort.", report.version_id: kept + "é" * 10}
    )

    with patch("onyx.skills.chat.read_versions_skill_md", read):
        accepted = accept_picked_skills(
            [
                [
                    SkillMention(name="report"),
                    SkillMention(name="triage"),
                    SkillMention(name="report"),
                    SkillMention(name="unreadable"),
                    SkillMention(name="missing"),
                ],
                [SkillMention(name="triage")],
            ],
            [triage, report, unreadable],
            uuid4(),
            Mock(),
        )

    # One read serves every message.
    read.assert_called_once()
    assert read.call_args.args[0] == {
        triage.version_id,
        report.version_id,
        unreadable.version_id,
    }
    # A repeat counts once; a skill the user cannot use or read is left out.
    assert [
        [(mention.name, mention.version_id) for mention in message.mentions]
        for message in accepted
    ] == [
        [("report", report.version_id), ("triage", triage.version_id)],
        [("triage", triage.version_id)],
    ]
    # Each pick has its `<skill>` message, cut with a note where the rest
    # begins, and the token count of that message.
    report_message, triage_message = accepted[0].skill_messages
    assert report_message.version_id == report.version_id
    assert report_message.content.startswith(
        f"<skill>\n<name>report</name>\n{kept}\n\n[SKILL.md continues"
    )
    assert f'name="report" and start_char={len(kept)}' in report_message.content
    assert triage_message.content == "<skill>\n<name>triage</name>\nSort.\n</skill>"
    tokenizer = get_tokenizer(None, None)
    assert [message.token_count for message in accepted[0].skill_messages] == [
        len(tokenizer.encode(report_message.content)),
        len(tokenizer.encode(triage_message.content)),
    ]


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
