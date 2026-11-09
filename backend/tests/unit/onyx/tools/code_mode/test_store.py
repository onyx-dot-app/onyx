import pytest
from pydantic import JsonValue

from onyx.llm.models import Message, ToolResultMessage, UserMessage
from onyx.tools.tool_implementations.code_mode.models import (
    CellClosing,
    CodeModeExecutionResult,
    CodeModeStatus,
    LostStoreWrites,
    StoreCommit,
    StoreSnapshot,
    json_text,
)
from onyx.tools.tool_implementations.code_mode.store import (
    MAX_COMMITTED_BYTES,
    MAX_LOST_KEYS_CHARS,
    MAX_PATH_KEY_CHARS,
    MAX_VALUE_DEPTH,
    ProgramStore,
    changed_writes,
    json_value,
    lost_store_writes,
    store_snapshot,
)


def stored_values(
    messages: list[Message], live: list[StoreCommit] | None = None
) -> dict[str, JsonValue]:
    return dict(store_snapshot(messages, live or []).values)


def _execution(
    call_id: str,
    commit: StoreCommit | None,
    status: CodeModeStatus = "completed",
) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=call_id,
        tool_name="execute_code",
        content="",
        details=CodeModeExecutionResult(
            cell_id=1, code="", status=status, commit=commit
        ),
    )


def test_stored_values_folds_writes_in_order() -> None:
    messages: list[Message] = [
        UserMessage(content="first"),
        _execution(
            "1", StoreCommit(ordinal=1, follows=0, writes={"a": 1, "b": [1, 2]})
        ),
        ToolResultMessage(tool_call_id="x", tool_name="run_python", content="{}"),
        _execution(
            "2", StoreCommit(ordinal=2, follows=1, writes={"a": 2, "c": {"k": "v"}})
        ),
        _execution("3", StoreCommit(ordinal=3, follows=2, writes={"b": None})),
    ]
    assert stored_values(messages) == {"a": 2, "c": {"k": "v"}}
    # A branch is the messages it holds; earlier prefixes give earlier stores.
    assert stored_values(messages[:2]) == {"a": 1, "b": [1, 2]}
    assert stored_values([]) == {}


def test_stored_values_reads_commit_records_and_closing_records() -> None:
    closed = CodeModeExecutionResult(
        cell_id=2,
        status="running",
        closing=CellClosing(
            reason="response_ended",
            status="completed",
            commit=StoreCommit(ordinal=2, follows=1, writes={"b": 2}),
        ),
    )
    messages: list[Message] = [
        _execution("1", StoreCommit(ordinal=1, follows=0, writes={"a": 1})),
        _execution("2", None, status="failed"),
        ToolResultMessage(
            tool_call_id="3", tool_name="execute_code", content="", details=closed
        ),
    ]
    assert stored_values(messages) == {"a": 1, "b": 2}


def test_stored_values_folds_commits_in_completion_order() -> None:
    # Saved in message order 2, 1; the commit with ordinal 2 completed last.
    messages: list[Message] = [
        _execution("b", StoreCommit(ordinal=2, follows=1, writes={"k": "b"})),
        _execution(
            "a", StoreCommit(ordinal=1, follows=0, writes={"k": "a", "only_a": 1})
        ),
    ]
    assert stored_values(messages) == {"k": "b", "only_a": 1}
    # A live commit already in the messages folds once; a newer one folds last.
    live = [
        StoreCommit(ordinal=2, follows=1, writes={"k": "b"}),
        StoreCommit(ordinal=3, follows=2, writes={"only_a": None}),
    ]
    assert stored_values(messages[1:], live) == {"k": "b"}
    assert stored_values(messages, live) == {"k": "b"}


def test_a_commit_applies_only_after_the_commit_it_follows() -> None:
    # The server stopped before it saved commit 1; commit 2 was made against it.
    messages: list[Message] = [
        _execution("2", StoreCommit(ordinal=2, follows=1, writes={"b": 2})),
    ]
    snapshot = store_snapshot(messages)
    assert (dict(snapshot.values), snapshot.last_ordinal, snapshot.last_applied) == (
        {},
        2,
        0,
    )
    # A dropped commit does not count toward the chat's limit on saved writes.
    assert snapshot.committed_bytes == 0
    # A later commit follows the store as it is, and takes the next ordinal.
    messages.append(_execution("3", StoreCommit(ordinal=3, follows=0, writes={"c": 3})))
    assert stored_values(messages) == {"c": 3}
    assert store_snapshot(messages).committed_bytes == len("c") + len("3")


def test_dropped_commits_are_listed_until_an_observation_reports_them() -> None:
    dropped = StoreCommit(ordinal=2, follows=1, writes={"b": 2, "gone": None})
    messages: list[Message] = [_execution("2", dropped)]
    assert store_snapshot(messages).dropped == (dropped,)
    lost = lost_store_writes(store_snapshot(messages).dropped)
    assert lost == LostStoreWrites(through=2, keys=("b", "gone"))
    # Commits that this response already reported are not listed again.
    assert store_snapshot(messages, reported_through=2).dropped == ()
    # Nor are commits that a saved observation reported.
    report = ToolResultMessage(
        tool_call_id="3",
        tool_name="execute_code",
        content="",
        details=CodeModeExecutionResult(
            cell_id=2, code="", status="completed", lost_store_writes=lost
        ),
    )
    assert store_snapshot([*messages, report]).dropped == ()


def test_the_report_of_dropped_commits_names_keys_within_a_bound() -> None:
    keys = [f"key_{index:03}_" + "x" * 40 for index in range(50)]
    lost = lost_store_writes(
        [StoreCommit(ordinal=2, follows=1, writes=dict.fromkeys(keys, 1))]
    )
    assert lost is not None
    assert 0 < len(lost.keys) < len(keys)
    assert lost.keys == tuple(keys[: len(lost.keys)])
    assert sum(len(key) + 2 for key in lost.keys) <= MAX_LOST_KEYS_CHARS
    assert lost.note.endswith(
        f", and {len(keys) - len(lost.keys)} more. load() "
        "returns the values from before those writes."
    )
    assert lost_store_writes([]) is None


def test_json_value_copies_and_converts_tuples() -> None:
    value = {"list": [1, (2, 3)], "nested": {"x": None, "y": 1.5, "z": True}}
    copied = json_value(value, "k", 1024)
    assert copied.value == {
        "list": [1, [2, 3]],
        "nested": {"x": None, "y": 1.5, "z": True},
    }
    assert copied.value is not value
    assert copied.text == json_text(copied.value)
    assert copied.size == len(copied.text.encode("utf-8"))


@pytest.mark.parametrize(
    "value",
    [
        {"k": [1, "é", None, {"a": [], "b": {}}], "t": True, "f": -1.5e-7},
        [],
        "x",
        [[[]], (1, 2)],
        # Escapes and multibyte characters make the JSON longer than the text.
        ['quote " and \\ backslash', "control \n\x00", "é, 中文 and 😀"],
        {"é" * 10: [10**30, 1e16, False]},
    ],
)
def test_json_value_limit_is_the_compact_json_size(value: JsonValue) -> None:
    size = len(json_text(json_value(value, "v", 10_000).value).encode("utf-8"))
    assert json_value(value, "v", size).size == size
    with pytest.raises(ValueError, match=f"v exceeds the limit of {size - 1} bytes"):
        json_value(value, "v", size - 1)


def test_json_value_rejects_lone_surrogates() -> None:
    with pytest.raises(ValueError):
        json_value({"k": "\ud800"}, "v", 1024)


def test_json_value_stops_at_its_limit_for_shared_references() -> None:
    value: list[object] = [1]
    for _ in range(64):
        value = [value, value]
    # 2**64 leaves as JSON; the copy stops once it passes 1 KB.
    with pytest.raises(ValueError, match="exceeds the limit of 1024 bytes"):
        json_value(value, "v", 1024)


def test_json_value_bounds_dict_keys_and_its_messages() -> None:
    long_key = "k" * 1_000_000
    with pytest.raises(ValueError, match="exceeds the limit of 64 bytes") as error:
        json_value({"a": {long_key: 1}}, "v", 64)
    assert f"at ['a'][{'k' * MAX_PATH_KEY_CHARS!r}...]" in str(error.value)
    # Its repr has 2**18 parts; the message names the key's type only.
    shared: object = ()
    for _ in range(18):
        shared = (shared, shared)
    with pytest.raises(TypeError, match=r"found a tuple key at \['a'\]\.$"):
        json_value({"a": {shared: 1}}, "v", 64)


def test_json_value_rejects_deep_nesting() -> None:
    value: list[object] = []
    for _ in range(MAX_VALUE_DEPTH - 1):
        value = [value]
    assert json_value(value, "v", 10_000).value == value
    with pytest.raises(ValueError, match=f"nests more than {MAX_VALUE_DEPTH} levels"):
        json_value([value], "v", 10_000)


def test_program_store_buffers_writes_over_a_snapshot() -> None:
    snapshot: dict[str, JsonValue] = {"kept": 1, "gone": 2, "same": [1], "int": 1}
    store = ProgramStore(StoreSnapshot(values=snapshot))
    store.store("new", {"a": 1})
    store.store("gone", None)
    store.store("same", [1])
    store.store("int", True)
    store.store("missing", None)
    assert store.load("new") == {"a": 1}
    assert store.load("gone") is None
    assert store.load("kept") == 1
    assert store.writes == {
        "new": {"a": 1},
        "gone": None,
        "same": [1],
        "int": True,
        "missing": None,
    }
    # A commit leaves out writes that keep a value as it was; True is not 1.
    assert changed_writes(snapshot, store.writes) == {
        "new": {"a": 1},
        "gone": None,
        "int": True,
    }
    assert snapshot == {"kept": 1, "gone": 2, "same": [1], "int": 1}


def test_snapshot_counts_committed_bytes_and_the_chat_limit_applies() -> None:
    messages: list[Message] = [
        _execution("1", StoreCommit(ordinal=1, follows=0, writes={"a": "xy"})),
        _execution("2", StoreCommit(ordinal=2, follows=1, writes={"a": None})),
    ]
    # 'a' + '"xy"', then the deleted key 'a'.
    assert store_snapshot(messages).committed_bytes == 5 + 1

    full = ProgramStore(
        StoreSnapshot(values={"k": "v"}, committed_bytes=MAX_COMMITTED_BYTES)
    )
    with pytest.raises(ValueError, match="bytes per chat"):
        full.store("new", "x")
    # Deleting and reading still work at the limit.
    full.store("k", None)
    assert full.load("k") is None
    assert full.writes == {"k": None}
