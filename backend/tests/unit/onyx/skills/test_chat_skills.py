from unittest.mock import Mock, patch
from uuid import uuid4

from onyx.agents.tools import ToolInvocation
from onyx.chat.mention_models import SkillMention
from onyx.chat.models import PromptMetadata
from onyx.db.models import User
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import AssistantMessage, TextContent, ToolCall, UserMessage
from onyx.prompts.skill_prompts import MENTIONED_SKILL_PROMPT, SKILLS_OMITTED_LINE
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.skills.chat import (
    MAX_CATALOG_DESCRIPTION_CHARS,
    MAX_SKILL_PROMPT_BYTES,
    accept_picked_skills,
    render_skills_catalog,
    used_skill_names,
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


def _line_tokens(line: str) -> int:
    # Codex's cost of a catalog line: four bytes a token, newline included.
    return -(-(len(line.encode()) + 1) // 4)


def test_catalog_gives_description_characters_to_each_skill_in_turn() -> None:
    skills = [_skill(f"skill-{index}", "y" * 400) for index in range(10)]
    skills.append(_skill("short", "Fits."))
    # 2% of 20,000 tokens is 400 tokens.
    catalog = render_skills_catalog(skills, 20_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    assert len(lines) == len(skills)
    assert sum(map(_line_tokens, lines)) <= 400
    assert lines[-1] == "- short: Fits."
    cut = [len(line.split(": ", 1)[1]) for line in lines[:-1]]
    # No skill takes the budget from the others: the cuts differ by at most
    # one token of characters.
    assert max(cut) - min(cut) <= 4
    assert 0 < min(cut) < 400
    # A description cut for the budget has no ellipsis.
    assert not any(line.endswith(".") for line in lines[:-1])


def test_catalog_budget_counts_utf8_bytes() -> None:
    # Two bytes a character: the character count fits the budget, the byte
    # count does not.
    skills = [_skill(f"skill-{index}", "é" * 300) for index in range(10)]

    catalog = render_skills_catalog(skills, 20_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    assert sum(map(_line_tokens, lines)) <= 400
    assert all(
        line.endswith("é") and len(line) < len("- skill-0: ") + 300 for line in lines
    )


def test_catalog_cut_below_the_cap_keeps_no_part_of_its_ellipsis() -> None:
    # 258 tokens fit the name and 1,023 description characters, but not the
    # capped 1,024-character description that ends in "...".
    catalog = render_skills_catalog([_skill("long", "x" * 5000)], 12_900)

    assert catalog is not None
    assert _catalog_lines(catalog) == ["- long: " + "x" * 1023]


def test_catalog_omits_skills_when_names_do_not_fit() -> None:
    skills = [_skill(f"skill-number-{index}") for index in range(100)]
    # 200 tokens; each name line costs 5.
    catalog = render_skills_catalog(skills, 10_000)

    assert catalog is not None
    lines = _catalog_lines(catalog)
    omitted = len(skills) - (len(lines) - 1)
    assert lines[-1] == SKILLS_OMITTED_LINE.format(count=omitted, skills="skills")
    assert sum(map(_line_tokens, lines)) <= 200
    assert lines[:-1] == [f"- {skill.name}" for skill in skills[: len(lines) - 1]]
    # The omitted line is charged: one more name would not fit with it.
    assert sum(map(_line_tokens, lines)) + 5 > 200


def test_catalog_lists_a_later_skill_that_fits_when_names_do_not() -> None:
    # 60 tokens: the second name does not fit after the first, the later
    # short names do.
    skills = [_skill("a" * 100), _skill("b" * 200), _skill("c"), _skill("d")]
    catalog = render_skills_catalog(skills, 3_000)

    assert catalog is not None
    assert _catalog_lines(catalog) == [
        f"- {'a' * 100}",
        "- c",
        "- d",
        SKILLS_OMITTED_LINE.format(count=1, skills="skill"),
    ]


def test_catalog_is_left_out_when_the_omitted_line_does_not_fit() -> None:
    # One token fits no skill and no omitted line.
    assert render_skills_catalog([_skill("pdf-report")], 50) is None


def test_skills_list_shows_the_full_description_capped() -> None:
    skills = [
        _skill("notes", "Write release notes.", short_description="Notes."),
        _skill("long", "z" * 2000),
    ]

    with (
        patch(
            "onyx.tools.tool_implementations.skills.skill_tools.get_session_with_current_tenant"
        ),
        patch(
            "onyx.tools.tool_implementations.skills.skill_tools.list_chat_skills",
            return_value=skills,
        ),
    ):
        result = SkillsListTool(User(id=uuid4()), built_ins=False)._run(
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
        return_value={
            (triage.version_id, ""): "Sort.",
            (report.version_id, ""): kept + "é" * 10,
        }
    )

    # One token per character keeps the test off the real tokenizer download.
    tokenizer = Mock()
    tokenizer.encode.side_effect = list
    with (
        patch("onyx.skills.chat.read_chat_skills_md", read),
        patch("onyx.skills.chat.get_tokenizer", return_value=tokenizer),
    ):
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
            sandbox=False,
        )

    # One read serves every message.
    read.assert_called_once()
    assert read.call_args.args[0] == {
        triage,
        report,
        unreadable,
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
    assert [message.token_count for message in accepted[0].skill_messages] == [
        len(report_message.content),
        len(triage_message.content),
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


def test_used_skill_names_come_from_skills_read_calls_and_picks() -> None:
    def pick(name: str, *, context: bool = True) -> UserMessage:
        return UserMessage(
            content=MENTIONED_SKILL_PROMPT.format(name=name, instructions="Do it."),
            metadata=PromptMetadata(is_input_context=context),
        )

    def read(name: str | int) -> AssistantMessage:
        return AssistantMessage(
            content=[
                TextContent(text=""),
                ToolCall(id=str(uuid4()), name="skills_read", arguments={"name": name}),
                ToolCall(id=str(uuid4()), name="skills_list", arguments={"name": "x"}),
            ]
        )

    assert used_skill_names(
        [
            pick("report"),
            read("triage"),
            read(3),
            read("triage"),
            pick("typed", context=False),
        ]
    ) == {"report": 1, "triage": 2}
