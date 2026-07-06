from onyx.chat.chat_state import ChatStateContainer


def test_state_container_carries_prompt_tokens() -> None:
    sc = ChatStateContainer()
    assert sc.prompt_tokens is None
    sc.set_prompt_tokens(1234)
    assert sc.prompt_tokens == 1234


def test_prompt_tokens_persists_on_assistant_message() -> None:
    from onyx.configs.constants import MessageType
    from onyx.db.models import ChatMessage

    msg = ChatMessage(
        message="hi",
        token_count=2,
        message_type=MessageType.ASSISTANT,
        prompt_tokens=4096,
    )
    assert msg.prompt_tokens == 4096
