from onyx.chat.chat_state import ChatStateContainer


def test_state_container_carries_prompt_tokens() -> None:
    sc = ChatStateContainer()
    assert sc.prompt_tokens is None
    sc.set_prompt_tokens(1234)
    assert sc.prompt_tokens == 1234
