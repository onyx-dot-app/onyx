from onyx.agents.agent_framework.query import query


def test_query_streams_chunks_from_llm(fake_llm) -> None:
    llm = fake_llm(["chunk-1", "chunk-2"])
    messages = [{"role": "user", "content": "hello"}]
    context = {}

    chunks = list(query(llm, messages, tools=[], context=context, tool_choice=None))

    assert chunks == ["chunk-1", "chunk-2"]
    assert llm.stream_calls and llm.stream_calls[0]["prompt"] == messages
