"""A chat turn gets the user's custom skills: their catalog in the prompt, the
skills tools, and the SKILL.md of each skill that a message picked, saved when
the message is accepted and sent after it on every later turn."""

import json
import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest

from onyx.agents.models import MessageDelivery
from onyx.chat.mention_models import RecordedMention, SkillMention
from onyx.configs.constants import MessageType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillSharePermission
from onyx.db.models import ChatMessage
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.server.features.skill.models import (
    SkillPatchRequest,
    SkillResponse,
    SkillUserShareRequest,
)
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    PendingChatMessageRequest,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.skills.bundle import build_skill_md
from onyx.skills.chat import MAX_SKILL_PROMPT_BYTES
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import (
    DATestChatSession,
    DATestUser,
    StreamedResponse,
)
from tests.integration.mock_services.mock_llm_server.models import (
    RecordedRequest,
    Reply,
    RequestConditions,
    ToolCall,
)

_SKILLS_TOOLS = {"skills_list", "skills_read"}


def _create_skill(user: DATestUser) -> tuple[SkillResponse, str, str]:
    """A skill, its description, and its whole SKILL.md."""
    description = f"Write release notes {uuid4().hex[:8]}."
    instructions = f"Group the notes by area. Marker {uuid4().hex}."
    skill = SkillManager.create_from_editor(
        user,
        name=f"chat-skill-{uuid4().hex[:8]}",
        description=description,
        instructions_markdown=instructions,
    )
    return skill, description, _skill_md(skill, description, instructions)


def _skill_md(skill: SkillResponse, description: str, instructions: str) -> str:
    """The SKILL.md that the editor saves, frontmatter included."""
    return build_skill_md(
        name=skill.name, description=description, instructions_markdown=instructions
    )


def test_chat_agent_reads_a_skill_from_its_catalog(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, description, skill_md = _create_skill(admin_user)
    chat_session_id = ChatSessionManager.create(user_performing_action=admin_user).id
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[
                ToolCall(
                    id="call_read", name="skills_read", arguments={"name": skill.name}
                )
            ],
            conditions=RequestConditions(
                offers=sorted(_SKILLS_TOOLS),
                prompt_contains=[f"- {skill.name}: {description}"],
            ),
        ),
        Reply(
            text="Notes grouped by area.",
            conditions=RequestConditions(has_results_for=["call_read"]),
        ),
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Write the release notes.",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == "Notes grouped by area."
    _, answer_request = mock_llm.requests_in("chat")
    # `skills_read` returns the whole SKILL.md, as Codex reads the file.
    assert answer_request.tool_result("call_read") == skill_md
    tool_packets = [
        packet["obj"]
        for packet in response.packets
        if packet["obj"]["type"]
        in (
            StreamingType.CUSTOM_TOOL_START.value,
            StreamingType.CUSTOM_TOOL_DELTA.value,
        )
    ]
    assert [(packet["type"], packet["tool_name"]) for packet in tool_packets] == [
        (StreamingType.CUSTOM_TOOL_START.value, "skills_read"),
        (StreamingType.CUSTOM_TOOL_DELTA.value, "skills_read"),
    ]
    assert tool_packets[1]["data"] == {"skill": skill.name}


def _mentioned(mentions: list[RecordedMention]) -> list[tuple[str, str]]:
    return [(mention.type, mention.name) for mention in mentions]


def _injected(name: str, skill_md: str) -> str:
    return f"<skill>\n<name>{name}</name>\n{skill_md}\n</skill>"


def _texts_after(request: RecordedRequest, question: str, count: int = 1) -> list[str]:
    """The user messages right after the question."""
    user_texts = [m.content for m in request.messages if m.role == "user"]
    start = user_texts.index(question) + 1
    return user_texts[start : start + count]


def test_picked_skill_pins_its_version_to_its_question(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, description, skill_md = _create_skill(admin_user)
    first_question = f"Use @{skill.name} for this week."
    second_question = f"Thanks. Use @{skill.name} for next week too."
    edited_instructions = f"Group the notes by team. Marker {uuid4().hex}."
    edited = _skill_md(skill, description, edited_instructions)
    read = ToolCall(id="call_read", name="skills_read", arguments={"name": skill.name})
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            text="First answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, skill_md)]
            ),
        ),
        Reply(
            tool_calls=[read],
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, edited)]
            ),
        ),
        Reply(
            text="Second answer.",
            conditions=RequestConditions(has_results_for=[read.id]),
        ),
    )

    first = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=first_question,
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )
    SkillManager.patch_custom(
        skill, admin_user, SkillPatchRequest(instructions_markdown=edited_instructions)
    )
    second = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=second_question,
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )

    assert first.error is None and second.error is None
    first_request, second_request, read_result = mock_llm.requests_in("chat")
    # The earlier question keeps the text it stored, on every turn.
    for request in (first_request, second_request):
        assert _texts_after(request, first_question) == [
            _injected(skill.name, skill_md)
        ]
    assert _texts_after(second_request, second_question) == [
        _injected(skill.name, edited)
    ]
    # `skills_read` reads the version the user runs now.
    assert read_result.tool_result(read.id) == edited
    user_messages = [
        message
        for message in ChatSessionManager.get_chat_history(chat_session, admin_user)
        if message.message_type == MessageType.USER
    ]
    assert [_mentioned(message.mentions) for message in user_messages] == [
        [("skill", skill.name)],
        [("skill", skill.name)],
    ]


def test_two_picked_skills_follow_their_question_in_picked_order(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    first_skill, _, first_skill_md = _create_skill(admin_user)
    second_skill, _, second_skill_md = _create_skill(admin_user)
    question = f"Use @{first_skill.name} and @{second_skill.name}."
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation("chat", Reply(text="Answer."))

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=question,
        user_performing_action=admin_user,
        mentions=[
            SkillMention(name=second_skill.name),
            SkillMention(name=first_skill.name),
        ],
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert _mentioned(response.mentions) == [
        ("skill", second_skill.name),
        ("skill", first_skill.name),
    ]
    (request,) = mock_llm.requests_in("chat")
    # The skills follow the question, in picked order.
    assert _texts_after(request, question, count=2) == [
        _injected(second_skill.name, second_skill_md),
        _injected(first_skill.name, first_skill_md),
    ]
    (question_row,) = [
        message
        for message in ChatSessionManager.get_chat_history(chat_session, admin_user)
        if message.message_type == MessageType.USER
    ]
    assert _mentioned(question_row.mentions) == [
        ("skill", second_skill.name),
        ("skill", first_skill.name),
    ]
    # Clients get the record of each pick, without what the message stores.
    detail = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
        headers=admin_user.headers,
    )
    detail.raise_for_status()
    (raw_question,) = [
        message
        for message in detail.json()["messages"]
        if message["message_type"] == MessageType.USER.value
    ]
    assert [set(mention) for mention in raw_question["mentions"]] == [
        {"type", "name", "version_id"}
    ] * 2


def test_regenerated_answer_uses_the_version_its_question_recorded(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, skill_md = _create_skill(admin_user)
    question = f"Use @{skill.name} for this week."
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    pinned = RequestConditions(prompt_contains=[_injected(skill.name, skill_md)])
    mock_llm.conversation(
        "chat",
        Reply(text="First answer.", conditions=pinned),
        Reply(text="Regenerated answer.", conditions=pinned),
    )

    first = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=question,
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )
    SkillManager.patch_custom(
        skill,
        admin_user,
        SkillPatchRequest(instructions_markdown=f"Edited. Marker {uuid4().hex}."),
    )
    (question_row,) = [
        message
        for message in ChatSessionManager.get_chat_history(chat_session, admin_user)
        if message.message_type == MessageType.USER
    ]
    # A send whose parent is the question regenerates its answer; it mentions
    # no skills, so the pinned skill comes from the recorded question.
    regenerated = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=question,
        user_performing_action=admin_user,
        parent_message_id=question_row.id,
    )

    assert first.error is None and regenerated.error is None
    _, regenerated_request = mock_llm.requests_in("chat")
    assert _texts_after(regenerated_request, question) == [
        _injected(skill.name, skill_md)
    ]


def test_deep_research_has_the_skills_and_reads_the_rest_of_a_long_pick(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    # Longer than the injected part, with a marker past it.
    instructions = "Check each section.\n" * 1000 + f"Marker {uuid4().hex}."
    skill = SkillManager.create_from_editor(
        admin_user,
        name=f"chat-skill-{uuid4().hex[:8]}",
        description="Review a long document.",
        instructions_markdown=instructions,
    )
    # The cut measures the whole file; its text is ASCII, so a byte is a
    # character.
    skill_md = _skill_md(skill, "Review a long document.", instructions)
    read_rest = ToolCall(
        id="call_read_rest",
        name="skills_read",
        arguments={"name": skill.name, "start_char": MAX_SKILL_PROMPT_BYTES},
    )
    research = ToolCall(
        id="call_research",
        name=RESEARCH_AGENT_TOOL_NAME,
        arguments={RESEARCH_AGENT_TASK_KEY: f"Apply the {skill.name} skill."},
    )
    child_read = ToolCall(
        id="call_child_read", name="skills_read", arguments={"name": skill.name}
    )
    mock_llm.conversation(
        "clarification",
        # Config can turn clarification off.
        Reply(
            tool_calls=[ToolCall(id="call_plan", name=GENERATE_PLAN_TOOL_NAME)],
            required=False,
        ),
        conditions=RequestConditions(offers=[GENERATE_PLAN_TOOL_NAME]),
    )
    mock_llm.conversation(
        "plan",
        Reply(text="1. Apply the skill."),
        conditions=RequestConditions(has_tools=False),
    )
    catalog_entry = f"- {skill.name}: Review a long document."
    mock_llm.conversation(
        "orchestrator",
        Reply(tool_calls=[read_rest, research]),
        Reply(
            tool_calls=[ToolCall(id="call_report", name=GENERATE_REPORT_TOOL_NAME)],
            conditions=RequestConditions(has_results_for=[read_rest.id, research.id]),
        ),
        conditions=RequestConditions(
            offers=[RESEARCH_AGENT_TOOL_NAME, *sorted(_SKILLS_TOOLS)],
            prompt_contains=[catalog_entry],
        ),
    )
    mock_llm.conversation(
        "research_agent",
        Reply(tool_calls=[child_read]),
        Reply(
            tool_calls=[
                ToolCall(id="call_child_report", name=GENERATE_REPORT_TOOL_NAME)
            ],
            conditions=RequestConditions(has_results_for=[child_read.id]),
        ),
        conditions=RequestConditions(
            offers=[*sorted(_SKILLS_TOOLS), GENERATE_REPORT_TOOL_NAME],
            does_not_offer=[RESEARCH_AGENT_TOOL_NAME],
            prompt_contains=[catalog_entry],
        ),
    )
    mock_llm.conversation(
        "intermediate_report",
        Reply(text="Intermediate findings."),
        conditions=RequestConditions(
            tool_choice="none", has_results_for=[child_read.id]
        ),
    )
    mock_llm.conversation(
        "final_report",
        Reply(text="Final report."),
        conditions=RequestConditions(has_tools=False, has_results_for=[read_rest.id]),
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=f"Use @{skill.name} on the report.",
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
        deep_research=True,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == "Final report."
    first_step, next_step = mock_llm.requests_in("orchestrator")
    # The question shows the start of the skill and where the rest begins.
    assert (
        f'name="{skill.name}" and start_char={MAX_SKILL_PROMPT_BYTES}'
        in first_step.prompt_text
    )
    assert next_step.tool_result(read_rest.id) == skill_md[MAX_SKILL_PROMPT_BYTES:]
    assert skill_md[:MAX_SKILL_PROMPT_BYTES] in first_step.prompt_text
    _, child_next_step = mock_llm.requests_in("research_agent")
    assert child_next_step.tool_result(child_read.id) == skill_md


def test_message_text_alone_mentions_no_skill(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, skill_md = _create_skill(admin_user)
    question = f"Compare @{skill.name} with the others."
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation("chat", Reply(text="Plain answer."))

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=question,
        user_performing_action=admin_user,
        # A name the user cannot use is ignored, not an error.
        mentions=[SkillMention(name=f"missing-{uuid4().hex[:8]}")],
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == "Plain answer."
    (request,) = mock_llm.requests_in("chat")
    assert "<skill>\n<name>" not in request.prompt_text
    assert skill_md not in request.prompt_text
    history = ChatSessionManager.get_chat_history(chat_session, admin_user)
    assert all(not message.mentions for message in history)


@pytest.mark.parametrize(
    "mentions",
    [
        pytest.param([{"type": "plugin", "name": "release-notes"}], id="kind"),
        pytest.param([{"type": "skill", "name": "Release Notes"}], id="name-grammar"),
        pytest.param([{"type": "skill", "name": "a" * 65}], id="name-length"),
        pytest.param(
            [{"type": "skill", "name": f"skill-{index}"} for index in range(21)],
            id="count",
        ),
    ],
)
def test_invalid_mentions_are_rejected(
    admin_user: DATestUser, mentions: list[dict[str, str]]
) -> None:
    chat_session_id = ChatSessionManager.create(user_performing_action=admin_user).id
    body = SendMessageRequest(
        message="Use @release-notes.", chat_session_id=chat_session_id
    ).model_dump(mode="json")
    pending_body = PendingChatMessageRequest(
        message="Then use @release-notes.", delivery=MessageDelivery.QUEUE
    ).model_dump(mode="json")

    responses = [
        client.post(
            f"{API_SERVER_URL}/chat/send-chat-message",
            json={**body, "mentions": mentions},
            headers=admin_user.headers,
        ),
        client.post(
            f"{API_SERVER_URL}/chat/chat-session/{chat_session_id}/pending-messages",
            json={**pending_body, "mentions": mentions},
            headers=admin_user.headers,
        ),
    ]

    for response in responses:
        assert response.status_code == 422, response.text
        assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_queued_message_uses_the_skills_mentioned_in_it(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, skill_md = _create_skill(admin_user)
    question = f"Then use @{skill.name}."
    gate = f"queued-{uuid4().hex}"
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation(
        "chat",
        Reply(text="First answer."),
        Reply(
            text="Queued answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, skill_md)]
            ),
            pause_after_first_chunk=gate,
        ),
    )
    first = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Start.",
        user_performing_action=admin_user,
    )
    assert first.error is None, f"Unexpected stream error: {first.error}"

    try:
        client.post(
            f"{API_SERVER_URL}/chat/chat-session/{chat_session.id}/pending-messages",
            json=PendingChatMessageRequest(
                message=question,
                delivery=MessageDelivery.QUEUE,
                mentions=[SkillMention(name=skill.name)],
            ).model_dump(mode="json"),
            headers=admin_user.headers,
        ).raise_for_status()
        # The queued turn starts on the server. Clients follow it as the
        # session's current stream, whose first packet names its question.
        deadline = time.monotonic() + 60
        while (
            stream := client.get(
                f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
                headers=admin_user.headers,
            ).json()["current_stream"]
        ) is None or stream["stream_id"] == first.assistant_message_id:
            assert time.monotonic() < deadline, "The queued message did not start"
            time.sleep(0.2)
        # The replay ends with the stream, so release the answer while it reads.
        threading.Timer(1.0, mock_llm.release_gate, args=[gate]).start()
        replay = client.get(
            f"{API_SERVER_URL}/chat/chat-session/{chat_session.id}/resume-stream",
            params={"stream_id": stream["stream_id"], "cursor": 0},
            headers=admin_user.headers,
        )
        replay.raise_for_status()
    finally:
        mock_llm.release_gate(gate)
    (id_info,) = [
        packet
        for packet in map(json.loads, filter(None, replay.text.splitlines()))
        if "reserved_assistant_message_id" in packet
    ]
    assert [(m["type"], m["name"]) for m in id_info["mentions"]] == [
        ("skill", skill.name)
    ]
    # The ID packet carries the record of the pick, without what the message
    # stores.
    assert set(id_info["mentions"][0]) == {"type", "name", "version_id"}

    deadline = time.monotonic() + 60
    while True:
        history = ChatSessionManager.get_chat_history(chat_session, admin_user)
        if any(message.message == "Queued answer." for message in history):
            break
        assert time.monotonic() < deadline, "The queued message was not answered"
        time.sleep(0.2)
    _, queued_request = mock_llm.requests_in("chat")
    assert _texts_after(queued_request, question) == [_injected(skill.name, skill_md)]
    assert [
        _mentioned(message.mentions)
        for message in history
        if message.message_type == MessageType.USER
    ] == [[], [("skill", skill.name)]]


def _send_during_response(
    mock_llm: MockLLMScript,
    chat_session_id: UUID,
    user: DATestUser,
    gate: str,
    sent: str,
    picked_skill: Callable[[], SkillResponse],
) -> StreamedResponse:
    """Start a response that pauses at `gate`, send `sent` with a pick of
    the skill that `picked_skill` gives once the response runs, and return
    the response once it finishes."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            held = executor.submit(
                ChatSessionManager.send_message,
                chat_session_id,
                "Start the report.",
                user,
            )
            deadline = time.monotonic() + 60
            while not mock_llm.requests_in("chat"):
                assert time.monotonic() < deadline, "The response did not start"
                time.sleep(0.2)
            client.post(
                f"{API_SERVER_URL}/chat/chat-session/{chat_session_id}/pending-messages",
                json=PendingChatMessageRequest(
                    message=sent,
                    delivery=MessageDelivery.SEND,
                    mentions=[SkillMention(name=picked_skill().name)],
                ).model_dump(mode="json"),
                headers=user.headers,
            ).raise_for_status()
        finally:
            mock_llm.release_gate(gate)
        return held.result(timeout=120)


def _paused_then_answers(gate: str) -> tuple[Reply, Reply]:
    """A first step that pauses at `gate` until a send arrives, then the
    answer."""
    return (
        Reply(
            text="Checking.",
            tool_calls=[ToolCall(id="call_list", name="skills_list")],
            pause_after_first_chunk=gate,
        ),
        Reply(
            text="Answer with the skill.",
            conditions=RequestConditions(has_results_for=["call_list"]),
        ),
    )


def test_message_sent_into_a_running_response_gets_its_picked_skill(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, skill_md = _create_skill(admin_user)
    sent = f"Also use @{skill.name} for the summary."
    gate = f"running-{uuid4().hex}"
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation(
        "chat", *_paused_then_answers(gate), Reply(text="Later answer.")
    )

    first = _send_during_response(
        mock_llm, chat_session.id, admin_user, gate, sent, lambda: skill
    )
    # The accepted message saved its skill text, so later turns need no read.
    SkillManager.delete_custom(skill, admin_user)
    later = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Continue.",
        user_performing_action=admin_user,
    )

    assert first.error is None and later.error is None
    assert first.full_message.endswith("Answer with the skill.")
    (accepted,) = [
        packet["obj"]
        for packet in first.packets
        if packet["obj"]["type"] == StreamingType.USER_MESSAGE.value
    ]
    assert accepted["message"] == sent
    assert [(m["type"], m["name"]) for m in accepted["mentions"]] == [
        ("skill", skill.name)
    ]
    # Clients get the record of the pick.
    assert set(accepted["mentions"][0]) == {"type", "name", "version_id"}
    _, next_step, later_request = mock_llm.requests_in("chat")
    for request in (next_step, later_request):
        assert _texts_after(request, sent) == [_injected(skill.name, skill_md)]


def test_a_send_picks_a_skill_created_while_its_response_runs(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    # The user has a skill when the response starts, so it has the skill
    # tools; they and the send's picks read the skills the user has now.
    _create_skill(admin_user)
    name = f"chat-skill-{uuid4().hex[:8]}"
    description = f"Write a summary {uuid4().hex[:8]}."
    instructions = f"Lead with the outcome. Marker {uuid4().hex}."
    created: list[SkillResponse] = []

    def create_during_response() -> SkillResponse:
        created.append(
            SkillManager.create_from_editor(
                admin_user,
                name=name,
                description=description,
                instructions_markdown=instructions,
            )
        )
        return created[0]

    sent = "Also use the new skill."
    gate = f"running-{uuid4().hex}"
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            text="Checking.",
            tool_calls=[ToolCall(id="call_list", name="skills_list")],
            pause_after_first_chunk=gate,
        ),
        Reply(
            tool_calls=[
                ToolCall(id="call_read", name="skills_read", arguments={"name": name})
            ],
            conditions=RequestConditions(has_results_for=["call_list"]),
        ),
        Reply(
            text="Answer with the skill.",
            conditions=RequestConditions(has_results_for=["call_read"]),
        ),
    )

    response = _send_during_response(
        mock_llm, chat_session.id, admin_user, gate, sent, create_during_response
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    (accepted,) = [
        packet["obj"]
        for packet in response.packets
        if packet["obj"]["type"] == StreamingType.USER_MESSAGE.value
    ]
    assert [(m["type"], m["name"]) for m in accepted["mentions"]] == [("skill", name)]
    skill_md = _skill_md(created[0], description, instructions)
    _, read_step, answer_step = mock_llm.requests_in("chat")
    assert _texts_after(read_step, sent) == [_injected(name, skill_md)]
    assert f"- {name}: {description}" in (read_step.tool_result("call_list") or "")
    assert answer_step.tool_result("call_read") == skill_md


def test_deleted_picked_skill_keeps_its_text_in_later_turns(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, skill_md = _create_skill(admin_user)
    question = f"Use @{skill.name} for this week."
    chat_session_id = ChatSessionManager.create(user_performing_action=admin_user).id
    mock_llm.conversation(
        "chat",
        Reply(
            text="First answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, skill_md)]
            ),
        ),
        Reply(text="Second answer."),
    )

    first = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message=question,
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )
    SkillManager.delete_custom(skill, admin_user)
    second = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Continue.",
        user_performing_action=admin_user,
    )

    assert first.error is None, f"Unexpected stream error: {first.error}"
    assert second.error is None, f"Unexpected stream error: {second.error}"
    assert second.full_message == "Second answer."
    # The question keeps the text it saved, as in Codex.
    _, second_request = mock_llm.requests_in("chat")
    assert _texts_after(second_request, question) == [_injected(skill.name, skill_md)]


def test_shared_chat_does_not_show_the_owners_skills(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, _ = _create_skill(admin_user)
    viewer = UserManager.create(name=f"chat-viewer-{uuid4().hex[:8]}")
    gate = f"shared-{uuid4().hex}"
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation("chat", *_paused_then_answers(gate), Reply(text="Answer."))
    running = _send_during_response(
        mock_llm, chat_session.id, admin_user, gate, "Also summarize.", lambda: skill
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=f"Use @{skill.name}.",
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )
    assert running.error is None, f"Unexpected stream error: {running.error}"
    assert response.error is None, f"Unexpected stream error: {response.error}"
    client.patch(
        f"{API_SERVER_URL}/chat/chat-session/{chat_session.id}",
        json={"sharing_status": "public"},
        headers=admin_user.headers,
    ).raise_for_status()

    def mentions(user: DATestUser, is_shared: bool) -> list[list[str]]:
        """The picks on each question, then on each message accepted during a
        response."""
        detail = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            params={"is_shared": str(is_shared).lower()},
            headers=user.headers,
        )
        detail.raise_for_status()
        body = detail.json()
        return [
            [mention["name"] for mention in message["mentions"]]
            for message in body["messages"]
            if message["message_type"] == MessageType.USER.value
        ] + [
            [mention["name"] for mention in packet["obj"]["mentions"]]
            for packets in body["packets"]
            for packet in packets
            if packet["obj"]["type"] == StreamingType.USER_MESSAGE.value
        ]

    assert mentions(admin_user, is_shared=False) == [[], [skill.name], [skill.name]]
    assert mentions(viewer, is_shared=True) == [[], [], []]


@pytest.fixture
def usage_only_incognito(admin_user: DATestUser) -> Generator[None, None, None]:
    security_url = f"{API_SERVER_URL}/admin/security"
    response = client.get(security_url, headers=admin_user.headers)
    response.raise_for_status()
    previous = {
        key: response.json()[key]
        for key in ("incognito_availability", "incognito_record_mode")
    }
    client.put(
        security_url,
        json={
            "incognito_availability": "everyone",
            "incognito_record_mode": "usage_only",
        },
        headers=admin_user.headers,
    ).raise_for_status()
    yield
    client.put(
        security_url, json=previous, headers=admin_user.headers
    ).raise_for_status()


def test_usage_only_incognito_keeps_skill_text_in_temporary_history(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    usage_only_incognito: None,  # noqa: ARG001
) -> None:
    skill, _, skill_md = _create_skill(admin_user)
    user = UserManager.create(name=f"incognito-skill-{uuid4().hex[:8]}")
    SkillManager.share(
        skill,
        admin_user,
        user_shares=[
            SkillUserShareRequest(
                user_id=UUID(user.id), permission=SkillSharePermission.VIEWER
            )
        ],
    )
    SkillManager.set_enabled(skill, user, enabled=True)
    question = f"Use @{skill.name} for this week."
    created = client.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json=ChatSessionCreationRequest(persona_id=0, incognito=True).model_dump(
            mode="json"
        ),
        headers=user.headers,
    )
    created.raise_for_status()
    chat_session_id = UUID(created.json()["chat_session_id"])
    mock_llm.conversation(
        "chat",
        Reply(text="First answer."),
        Reply(text="Second answer."),
        Reply(text="Third answer."),
        Reply(text="Regenerated answer."),
    )
    try:
        first = ChatSessionManager.send_message(
            chat_session_id=chat_session_id,
            message=question,
            user_performing_action=user,
            mentions=[SkillMention(name=skill.name)],
        )
        SkillManager.patch_custom(
            skill,
            admin_user,
            SkillPatchRequest(instructions_markdown=f"Edited {uuid4().hex}."),
        )
        second = ChatSessionManager.send_message(
            chat_session_id=chat_session_id,
            message="Continue.",
            user_performing_action=user,
        )
        SkillManager.share(skill, admin_user, user_shares=[])
        third = ChatSessionManager.send_message(
            chat_session_id=chat_session_id,
            message="Continue again.",
            user_performing_action=user,
        )
        history = ChatSessionManager.get_chat_history(
            DATestChatSession(
                id=chat_session_id, persona_id=0, description="incognito"
            ),
            user,
        )
        question_row = next(
            message for message in history if message.message_type == MessageType.USER
        )
        with get_session_with_current_tenant() as db_session:
            stored_row = db_session.get(ChatMessage, question_row.id)
            assert stored_row is not None
            stored_skill_messages = stored_row.skill_messages
        regenerated = ChatSessionManager.send_message(
            chat_session_id=chat_session_id,
            message=question,
            user_performing_action=user,
            parent_message_id=question_row.id,
        )
    finally:
        client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session_id}",
            headers=user.headers,
        ).raise_for_status()

    for response in (first, second, third, regenerated):
        assert response.error is None, f"Unexpected stream error: {response.error}"
    # The content-free question row keeps the pick for display, but no text.
    assert _mentioned(question_row.mentions) == [("skill", skill.name)]
    assert stored_skill_messages == []
    # The skill text is conversation content, so temporary history keeps it:
    # after an edit and after access ends, later turns and a regeneration
    # still get the text the question stored.
    for request in mock_llm.requests_in("chat"):
        assert _texts_after(request, question) == [_injected(skill.name, skill_md)]


def test_user_without_custom_skills_gets_no_skills_tools(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    # The admin's skills from other tests are not visible to this user.
    _create_skill(admin_user)
    user = UserManager.create(name=f"no-skills-{uuid4().hex[:8]}")
    chat_session_id = ChatSessionManager.create(user_performing_action=user).id
    mock_llm.conversation(
        "chat",
        Reply(
            text="Plain answer.",
            conditions=RequestConditions(does_not_offer=sorted(_SKILLS_TOOLS)),
        ),
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Hello.",
        user_performing_action=user,
    )

    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert response.full_message == "Plain answer."
    (request,) = mock_llm.requests_in("chat")
    assert "<skills_instructions>" not in request.prompt_text
