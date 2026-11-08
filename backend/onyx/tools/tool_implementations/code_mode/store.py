"""Values that code mode programs keep for later executions with store() and load().

The store of a chat is not saved anywhere of its own. A cell that ends by itself
(completes, or stops at an uncaught exception) commits its writes; the saved
result that reports the end keeps the commit (`CellWindow.commit`, on an
observation or its closing record) with its place in the completion order. The
store that a program sees is the fold of those commits, in that order, over the
recorded messages of the conversation. So the store follows chat branches,
survives restarts, and keeps values that history compaction hides from the
model.
"""

import math
from collections.abc import Callable, Iterable, Mapping

from pydantic import JsonValue
from pydantic_monty import MontyClassProxy

from onyx.llm.models import Message
from onyx.tools.tool_implementations.code_mode.models import (
    StoreCommit,
    StoreSnapshot,
    code_mode_results,
    entry_bytes,
    json_text,
)

STORE_FUNCTION = "store"
LOAD_FUNCTION = "load"

STORE_STUBS = '''def store(key: str, value: Any) -> None:
    """Save a JSON value for later execute_code calls in this chat; None deletes the key."""
    ...


def load(key: str) -> Any:
    """The value stored under `key`, or None."""
    ...'''

MAX_STORED_VALUE_BYTES = 256 * 1024
MAX_STORE_BYTES = 1024 * 1024
# Bytes of all commits that a chat saves in its history. The store holds at most
# MAX_STORE_BYTES, so this allows rewriting a full store 16 times, and it bounds
# what the store adds to a chat's saved messages.
MAX_COMMITTED_BYTES = 16 * MAX_STORE_BYTES
MAX_STORE_KEY_CHARS = 200

JSON_TYPES_TEXT = "str, int, float, bool, None, list, or dict with str keys"


def _type_name(value: object) -> str:
    # Instances of classes that the program defines arrive as proxies.
    return value.name if isinstance(value, MontyClassProxy) else type(value).__name__


def json_value(value: object, what: str, path: str = "") -> JsonValue:
    """A copy of `value` as strict JSON data; raises TypeError for anything else.

    `what` names the value in error messages. Tuples become lists; NaN, infinity
    and dict keys that are not str are rejected.
    """
    where = f" at {path}" if path else ""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(
                f"{what} must be JSON data; {value} is not a JSON number{where}."
            )
        return value
    if isinstance(value, (list, tuple)):
        return [
            json_value(item, what, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        copied: dict[str, JsonValue] = {}
        for item_key, item in value.items():
            if not isinstance(item_key, str):
                raise TypeError(
                    f"{what} must be JSON data; dict keys must be str, found "
                    f"{type(item_key).__name__} key {item_key!r}{where}."
                )
            copied[item_key] = json_value(item, what, f"{path}[{item_key!r}]")
        return copied
    raise TypeError(
        f"{what} must be JSON data ({JSON_TYPES_TEXT}); found "
        f"{_type_name(value)}{where}. Convert it first, for example to a dict."
    )


def _commits(messages: Iterable[Message]) -> list[StoreCommit]:
    """The store commits that `messages` record."""
    return [
        window.commit
        for _, details in code_mode_results(messages)
        for window in details.windows()
        if window.commit is not None
    ]


def store_snapshot(
    messages: Iterable[Message], live: Iterable[StoreCommit] = ()
) -> StoreSnapshot:
    """The store after the commits recorded in `messages` and the `live` commits
    not yet recorded there, folded in completion order.

    The fold does not depend on message order, so the saved history gives the
    store that programs saw while the response ran.
    """
    recorded = _commits(messages)
    known = {commit.ordinal for commit in recorded}
    pending = [commit for commit in live if commit.ordinal not in known]
    store: dict[str, JsonValue] = {}
    committed_bytes = 0
    last_ordinal = 0
    for commit in sorted([*recorded, *pending], key=lambda commit: commit.ordinal):
        for key, value in commit.writes.items():
            if value is None:
                store.pop(key, None)
            else:
                store[key] = value
        committed_bytes += commit.size_bytes
        last_ordinal = commit.ordinal
    return StoreSnapshot(
        values=store, committed_bytes=committed_bytes, last_ordinal=last_ordinal
    )


def _differs(before: JsonValue, after: JsonValue) -> bool:
    if before is None or after is None:
        return before is not after
    # Serialized, so that 1, 1.0 and True stay distinct.
    return json_text(before) != json_text(after)


def changed_writes(
    store: Mapping[str, JsonValue], writes: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """The `writes` that change `store`; a commit saves only these."""
    return {
        key: value for key, value in writes.items() if _differs(store.get(key), value)
    }


def _valid_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError(f"Store keys must be str, not {type(key).__name__}.")
    if not key or len(key) > MAX_STORE_KEY_CHARS:
        raise ValueError(
            f"Store keys must have 1 to {MAX_STORE_KEY_CHARS} characters; "
            f"found {len(key)}."
        )
    return key


class ProgramStore:
    """The store as one program sees it: a snapshot plus the program's writes.

    The writes take effect for later programs only when this program commits them.
    """

    def __init__(self, snapshot: StoreSnapshot) -> None:
        self._snapshot = snapshot
        self._values = dict(snapshot.values)
        self._sizes = {
            key: entry_bytes(key, value) for key, value in self._values.items()
        }
        self._total = sum(self._sizes.values())
        self._writes: dict[str, JsonValue] = {}
        # Bytes that each changed key adds to the commit.
        self._write_sizes: dict[str, int] = {}

    @property
    def writes(self) -> dict[str, JsonValue]:
        """The last value written to each key, None deleting it; also writes that
        do not change the store."""
        return dict(self._writes)

    @property
    def functions(self) -> dict[str, Callable[..., JsonValue]]:
        """store() and load() as the program calls them."""
        return {STORE_FUNCTION: self.store, LOAD_FUNCTION: self.load}

    def load(self, key: object) -> JsonValue:
        return self._values.get(_valid_key(key))

    def store(self, key: object, value: object) -> None:
        valid_key = _valid_key(key)
        stored = json_value(value, f'Cannot store "{valid_key}": the value')
        write_bytes = entry_bytes(valid_key, stored)
        value_bytes = write_bytes - len(valid_key.encode("utf-8"))
        if value_bytes > MAX_STORED_VALUE_BYTES:
            raise ValueError(
                f'Cannot store "{valid_key}": the value is {value_bytes} bytes as '
                f"JSON; the limit is {MAX_STORED_VALUE_BYTES} bytes per value."
            )
        size = 0 if stored is None else write_bytes
        total = self._total - self._sizes.get(valid_key, 0) + size
        if total > MAX_STORE_BYTES and total > self._total:
            raise ValueError(
                f'Cannot store "{valid_key}": the store would hold {total} bytes; '
                f"the limit is {MAX_STORE_BYTES} bytes. Store less, or delete keys "
                "with store(key, None)."
            )
        write_size = (
            write_bytes if _differs(self._snapshot.values.get(valid_key), stored) else 0
        )
        committed = (
            self._snapshot.committed_bytes
            + sum(self._write_sizes.values())
            - self._write_sizes.get(valid_key, 0)
            + write_size
        )
        if stored is not None and committed > MAX_COMMITTED_BYTES:
            raise ValueError(
                f'Cannot store "{valid_key}": this chat has saved '
                f"{self._snapshot.committed_bytes} bytes of store writes; the limit "
                f"is {MAX_COMMITTED_BYTES} bytes per chat. Values stored earlier "
                "stay available with load(); start a new chat to store more."
            )
        self._total = total
        if write_size:
            self._write_sizes[valid_key] = write_size
        else:
            self._write_sizes.pop(valid_key, None)
        if stored is None:
            self._values.pop(valid_key, None)
            self._sizes.pop(valid_key, None)
        else:
            self._values[valid_key] = stored
            self._sizes[valid_key] = size
        self._writes[valid_key] = stored
