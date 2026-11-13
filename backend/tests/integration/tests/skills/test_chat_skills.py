"""A chat turn gets the user's custom skills: their catalog in the prompt, the
skills tools, and the SKILL.md of each skill the user mentioned in a question,
pinned to the version the question recorded."""

import json
import threading
import time
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest

from onyx.agents.models import MessageDelivery
from onyx.chat.mention_models import RecordedMention, SkillMention
from onyx.configs.constants import MessageType
from onyx.db.enums import SkillSharePermission
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
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestChatSession, DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    RecordedRequest,
    Reply,
    RequestConditions,
    ToolCall,
)

_SKILLS_TOOLS = {"skills_list", "skills_read"}


def _create_skill(user: DATestUser) -> tuple[SkillResponse, str, str]:
    description = f"Write release notes {uuid4().hex[:8]}."
    instructions = f"Group the notes by area. Marker {uuid4().hex}."
    skill = SkillManager.create_from_editor(
        user,
        name=f"chat-skill-{uuid4().hex[:8]}",
        description=description,
        instructions_markdown=instructions,
    )
    return skill, description, instructions


def test_chat_agent_reads_a_skill_from_its_catalog(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, description, instructions = _create_skill(admin_user)
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
    assert answer_request.tool_result("call_read") == instructions
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


def _injected(name: str, instructions: str) -> str:
    return f"<skill>\n<name>{name}</name>\n{instructions}\n</skill>"


def _texts_before(request: RecordedRequest, question: str, count: int = 1) -> list[str]:
    """The user messages right before the question."""
    user_texts = [m.content for m in request.messages if m.role == "user"]
    end = user_texts.index(question)
    return user_texts[end - count : end]


def test_picked_skill_pins_its_version_to_its_question(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, instructions = _create_skill(admin_user)
    first_question = f"Use @{skill.name} for this week."
    second_question = f"Thanks. Use @{skill.name} for next week too."
    edited = f"Group the notes by team. Marker {uuid4().hex}."
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation(
        "chat",
        Reply(
            text="First answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, instructions)]
            ),
        ),
        Reply(
            text="Second answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, edited)]
            ),
        ),
    )

    first = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=first_question,
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )
    SkillManager.patch_custom(
        skill, admin_user, SkillPatchRequest(instructions_markdown=edited)
    )
    second = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=second_question,
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )

    assert first.error is None and second.error is None
    first_request, second_request = mock_llm.requests_in("chat")
    # The earlier question keeps the version it recorded, on every turn.
    for request in (first_request, second_request):
        assert _texts_before(request, first_question) == [
            _injected(skill.name, instructions)
        ]
    assert _texts_before(second_request, second_question) == [
        _injected(skill.name, edited)
    ]
    user_messages = [
        message
        for message in ChatSessionManager.get_chat_history(chat_session, admin_user)
        if message.message_type == MessageType.USER
    ]
    assert [_mentioned(message.mentions) for message in user_messages] == [
        [("skill", skill.name)],
        [("skill", skill.name)],
    ]


def test_two_picked_skills_precede_their_question(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    first_skill, _, first_instructions = _create_skill(admin_user)
    second_skill, _, second_instructions = _create_skill(admin_user)
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
    # The skills come right before the question, in picked order.
    assert _texts_before(request, question, count=2) == [
        _injected(second_skill.name, second_instructions),
        _injected(first_skill.name, first_instructions),
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


def test_regenerated_answer_uses_the_version_its_question_recorded(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, instructions = _create_skill(admin_user)
    question = f"Use @{skill.name} for this week."
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    pinned = RequestConditions(prompt_contains=[_injected(skill.name, instructions)])
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
    assert _texts_before(regenerated_request, question) == [
        _injected(skill.name, instructions)
    ]


def test_message_text_alone_mentions_no_skill(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, instructions = _create_skill(admin_user)
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
    assert instructions not in request.prompt_text
    history = ChatSessionManager.get_chat_history(chat_session, admin_user)
    assert all(not message.mentions for message in history)


def test_unsupported_mention_type_is_rejected(admin_user: DATestUser) -> None:
    chat_session_id = ChatSessionManager.create(user_performing_action=admin_user).id

    body = SendMessageRequest(
        message="Use @release-notes.",
        chat_session_id=chat_session_id,
        mentions=[SkillMention(name="release-notes")],
    ).model_dump(mode="json")
    # Only the mention's kind makes this valid request invalid.
    body["mentions"][0]["type"] = "plugin"

    response = client.post(
        f"{API_SERVER_URL}/chat/send-chat-message",
        json=body,
        headers=admin_user.headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_queued_message_uses_the_skills_mentioned_in_it(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, instructions = _create_skill(admin_user)
    question = f"Then use @{skill.name}."
    gate = f"queued-{uuid4().hex}"
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation(
        "chat",
        Reply(text="First answer."),
        Reply(
            text="Queued answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, instructions)]
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

    deadline = time.monotonic() + 60
    while True:
        history = ChatSessionManager.get_chat_history(chat_session, admin_user)
        if any(message.message == "Queued answer." for message in history):
            break
        assert time.monotonic() < deadline, "The queued message was not answered"
        time.sleep(0.2)
    _, queued_request = mock_llm.requests_in("chat")
    assert _texts_before(queued_request, question) == [
        _injected(skill.name, instructions)
    ]
    assert [
        _mentioned(message.mentions)
        for message in history
        if message.message_type == MessageType.USER
    ] == [[], [("skill", skill.name)]]


def test_deleted_mentioned_skill_does_not_fail_later_turns(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, instructions = _create_skill(admin_user)
    question = f"Use @{skill.name} for this week."
    chat_session_id = ChatSessionManager.create(user_performing_action=admin_user).id
    mock_llm.conversation(
        "chat",
        Reply(
            text="First answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, instructions)]
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
    _, second_request = mock_llm.requests_in("chat")
    (unavailable,) = _texts_before(second_request, question)
    assert unavailable.startswith(f"<skill>\n<name>{skill.name}</name>\n")
    assert "no longer available" in unavailable
    assert instructions not in second_request.prompt_text


def test_unshared_skill_stops_reaching_its_old_questions(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, instructions = _create_skill(admin_user)
    user = UserManager.create(name=f"skill-viewer-{uuid4().hex[:8]}")
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
    chat_session_id = ChatSessionManager.create(user_performing_action=user).id
    mock_llm.conversation(
        "chat",
        Reply(
            text="First answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, instructions)]
            ),
        ),
        Reply(text="Second answer."),
    )

    first = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message=question,
        user_performing_action=user,
        mentions=[SkillMention(name=skill.name)],
    )
    SkillManager.share(skill, admin_user, user_shares=[])
    second = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Continue.",
        user_performing_action=user,
    )

    assert first.error is None, f"Unexpected stream error: {first.error}"
    assert second.error is None, f"Unexpected stream error: {second.error}"
    _, second_request = mock_llm.requests_in("chat")
    (unavailable,) = _texts_before(second_request, question)
    assert unavailable.startswith(f"<skill>\n<name>{skill.name}</name>\n")
    assert "no longer available" in unavailable
    assert instructions not in second_request.prompt_text


def test_shared_chat_does_not_show_the_owners_skills(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    skill, _, _ = _create_skill(admin_user)
    viewer = UserManager.create(name=f"chat-viewer-{uuid4().hex[:8]}")
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)
    mock_llm.conversation("chat", Reply(text="Answer."))
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=f"Use @{skill.name}.",
        user_performing_action=admin_user,
        mentions=[SkillMention(name=skill.name)],
    )
    assert response.error is None, f"Unexpected stream error: {response.error}"
    client.patch(
        f"{API_SERVER_URL}/chat/chat-session/{chat_session.id}",
        json={"sharing_status": "public"},
        headers=admin_user.headers,
    ).raise_for_status()

    def mentions(user: DATestUser, is_shared: bool) -> list[list[str]]:
        detail = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session.id}",
            params={"is_shared": str(is_shared).lower()},
            headers=user.headers,
        )
        detail.raise_for_status()
        return [
            [mention["name"] for mention in message["mentions"]]
            for message in detail.json()["messages"]
            if message["message_type"] == MessageType.USER.value
        ]

    assert mentions(admin_user, is_shared=False) == [[skill.name]]
    assert mentions(viewer, is_shared=True) == [[]]


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


def test_usage_only_incognito_keeps_mentioned_skill_text_in_temporary_history(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    usage_only_incognito: None,  # noqa: ARG001
) -> None:
    skill, _, instructions = _create_skill(admin_user)
    question = f"Use @{skill.name} for this week."
    created = client.post(
        f"{API_SERVER_URL}/chat/create-chat-session",
        json=ChatSessionCreationRequest(persona_id=0, incognito=True).model_dump(
            mode="json"
        ),
        headers=admin_user.headers,
    )
    created.raise_for_status()
    chat_session_id = UUID(created.json()["chat_session_id"])
    mock_llm.conversation(
        "chat",
        Reply(
            text="First answer.",
            conditions=RequestConditions(
                prompt_contains=[_injected(skill.name, instructions)]
            ),
        ),
        Reply(text="Second answer."),
    )
    try:
        first = ChatSessionManager.send_message(
            chat_session_id=chat_session_id,
            message=question,
            user_performing_action=admin_user,
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
            user_performing_action=admin_user,
        )
        history = ChatSessionManager.get_chat_history(
            DATestChatSession(
                id=chat_session_id, persona_id=0, description="incognito"
            ),
            admin_user,
        )
    finally:
        client.delete(
            f"{API_SERVER_URL}/chat/delete-chat-session/{chat_session_id}",
            headers=admin_user.headers,
        ).raise_for_status()

    assert first.error is None and second.error is None
    _, second_request = mock_llm.requests_in("chat")
    assert _texts_before(second_request, question) == [
        _injected(skill.name, instructions)
    ]
    # The content-free question row keeps the skill it mentioned, so the
    # branch finds its skill text in temporary history.
    assert [
        _mentioned(message.mentions)
        for message in history
        if message.message_type == MessageType.USER
    ] == [[("skill", skill.name)], []]


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
