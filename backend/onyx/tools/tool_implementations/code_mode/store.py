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
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import NamedTuple

from pydantic import JsonValue
from pydantic_monty import MontyClassProxy

from onyx.llm.models import Message
from onyx.tools.tool_implementations.code_mode.models import (
    LostStoreWrites,
    StoreCommit,
    StoreSnapshot,
    code_mode_results,
    entry_bytes,
    json_text,
)

STORE_FUNCTION = "store"
LOAD_FUNCTION = "load"
STORE_FUNCTIONS: frozenset[str] = frozenset({STORE_FUNCTION, LOAD_FUNCTION})

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
# Characters of the keys that a note on dropped commits names.
MAX_LOST_KEYS_CHARS = 400
# Levels of nested lists and dicts in a value that leaves the sandbox. Monty
# replaces values below 200 levels with a placeholder string, so a lower limit
# rejects them instead.
MAX_VALUE_DEPTH = 100
# Characters of each dict key that an error message shows in a value's path.
MAX_PATH_KEY_CHARS = 40

JSON_TYPES_TEXT = "str, int, float, bool, None, list, or dict with str keys"


def _type_name(value: object) -> str:
    # Instances of classes that the program defines arrive as proxies.
    return value.name if isinstance(value, MontyClassProxy) else type(value).__name__


class JsonCopy(NamedTuple):
    """A sandbox value copied as JSON data, with its compact JSON text
    (`json_text`) and that text's UTF-8 bytes."""

    value: JsonValue
    text: str
    size: int


def json_value(value: object, what: str, max_bytes: int) -> JsonCopy:
    """A copy of `value` as strict JSON data of at most `max_bytes` as compact JSON.

    Every sandbox value that the host copies or saves goes through this copy.
    `what` names the value in error messages. Tuples become lists. Raises
    TypeError for data that is not JSON (also NaN, infinity and dict keys that
    are not str), and ValueError when the copy would exceed `max_bytes` or nest
    deeper than MAX_VALUE_DEPTH, or holds a lone surrogate. Error messages show
    at most MAX_PATH_KEY_CHARS of each key.

    Sandbox values can share references, so `x = [x, x]` doubles the JSON size
    with each step at no cost to the program. The copy walks with an explicit
    stack and counts a lower bound of the JSON bytes as it copies, so it stops
    after at most `max_bytes` of work and memory. It then encodes the copy once
    for the exact size; a value that only that check rejects gets a message
    without the path.
    """
    size = 0
    # The containers being copied, from the root down, with their remaining
    # items; `keys` holds the key of the item that each one is copying.
    open_items: list[
        tuple[list[JsonValue] | dict[str, JsonValue], Iterator[tuple[object, object]]]
    ] = []
    keys: list[object] = []

    def where() -> str:
        # Long keys are cut so that the message stays small.
        path = "".join(
            f"[{key[:MAX_PATH_KEY_CHARS]!r}...]"
            if isinstance(key, str) and len(key) > MAX_PATH_KEY_CHARS
            else f"[{key!r}]"
            for key in keys
        )
        return f" at {path}" if path else ""

    def count(more: int) -> None:
        nonlocal size
        size += more
        if size > max_bytes:
            raise ValueError(
                f"{what} exceeds the limit of {max_bytes} bytes as JSON{where()}."
            )

    def count_scalar(item: JsonValue) -> None:
        # A lower bound: a str has its quotes and at least one byte per
        # character, a number at least one digit.
        if isinstance(item, str):
            count(len(item) + 2)
        elif item is None or item is True:
            count(4)
        else:
            count(5 if item is False else 1)

    def copy(item: object) -> JsonValue:
        """`item` if it is a JSON scalar; else an empty copy that the walk fills."""
        if item is None or isinstance(item, (str, bool, int, float)):
            if isinstance(item, float) and not math.isfinite(item):
                raise TypeError(
                    f"{what} must be JSON data; {item} is not a JSON number{where()}."
                )
            count_scalar(item)
            return item
        if not isinstance(item, (list, tuple, dict)):
            raise TypeError(
                f"{what} must be JSON data ({JSON_TYPES_TEXT}); found "
                f"{_type_name(item)}{where()}. Convert it first, for example to a dict."
            )
        if len(open_items) >= MAX_VALUE_DEPTH:
            raise ValueError(
                f"{what} nests more than {MAX_VALUE_DEPTH} levels deep{where()}."
            )
        # Brackets and commas; a dict also has a colon per item.
        count(1 + max(len(item), 1) + (len(item) if isinstance(item, dict) else 0))
        copied: list[JsonValue] | dict[str, JsonValue]
        if isinstance(item, dict):
            copied = {}
            open_items.append((copied, iter(item.items())))
        else:
            copied = []
            open_items.append((copied, enumerate(item)))
        keys.append(None)
        return copied

    root = copy(value)
    while open_items:
        container, items = open_items[-1]
        entry = next(items, None)
        if entry is None:
            open_items.pop()
            keys.pop()
            continue
        key, item = entry
        if isinstance(container, list):
            keys[-1] = key
            container.append(copy(item))
            continue
        if not isinstance(key, str):
            # Names the dict and the key type only: the repr of an unchecked key
            # is unbounded.
            keys.pop()
            raise TypeError(
                f"{what} must be JSON data; dict keys must be str, found a "
                f"{_type_name(key)} key{where()}."
            )
        keys[-1] = key
        count_scalar(key)
        container[key] = copy(item)
    text = json_text(root)
    exact = len(text.encode("utf-8"))
    if exact > max_bytes:
        raise ValueError(f"{what} exceeds the limit of {max_bytes} bytes as JSON.")
    return JsonCopy(value=root, text=text, size=exact)


def store_snapshot(
    messages: Iterable[Message],
    live: Iterable[StoreCommit] = (),
    reported_through: int = 0,
) -> StoreSnapshot:
    """The store after the commits recorded in `messages` and the `live` commits
    not yet recorded there, folded in completion order.

    The fold does not depend on message order, so the saved history gives the
    store that programs saw while the response ran. A commit applies only after
    the commit it follows, so the store is always a prefix of the commit order:
    when the server stops before it saves a commit, later commits that were
    made against it do not apply, and do not count toward `committed_bytes`.
    The snapshot lists them in `dropped` until a saved observation reports them
    (`CodeModeExecutionResult.lost_store_writes`) or `reported_through` covers
    their ordinals. A report covers every dropped commit up to its highest
    ordinal: a later commit takes a higher ordinal, so a commit that the store
    drops later is never below a report.
    """
    results = [details for _, details in code_mode_results(messages)]
    recorded = [
        window.commit
        for details in results
        for window in details.windows()
        if window.commit is not None
    ]
    reported_through = max(
        reported_through,
        *(
            details.lost_store_writes.through
            for details in results
            if details.lost_store_writes is not None
        ),
        0,
    )
    known = {commit.ordinal for commit in recorded}
    pending = [commit for commit in live if commit.ordinal not in known]
    store: dict[str, JsonValue] = {}
    committed_bytes = 0
    last_ordinal = 0
    last_applied = 0
    dropped: list[StoreCommit] = []
    for commit in sorted([*recorded, *pending], key=lambda commit: commit.ordinal):
        last_ordinal = commit.ordinal
        if commit.follows != last_applied:
            if commit.ordinal > reported_through:
                dropped.append(commit)
            continue
        committed_bytes += commit.size_bytes
        for key, value in commit.writes.items():
            if value is None:
                store.pop(key, None)
            else:
                store[key] = value
        last_applied = commit.ordinal
    return StoreSnapshot(
        values=store,
        committed_bytes=committed_bytes,
        last_ordinal=last_ordinal,
        last_applied=last_applied,
        dropped=tuple(dropped),
    )


def lost_store_writes(dropped: Iterable[StoreCommit]) -> LostStoreWrites | None:
    """The report of `dropped` commits, naming their keys within
    MAX_LOST_KEYS_CHARS; None when there are none."""
    commits = list(dropped)
    if not commits:
        return None
    keys = list(dict.fromkeys(key for commit in commits for key in commit.writes))
    named: list[str] = []
    chars = 0
    for key in keys:
        chars += len(key) + 2
        if named and chars > MAX_LOST_KEYS_CHARS:
            break
        named.append(key)
    return LostStoreWrites(
        through=max(commit.ordinal for commit in commits),
        keys=tuple(named),
        more_keys=len(keys) - len(named),
    )


def _differs(
    before: JsonValue, after: JsonValue, after_text: str | None = None
) -> bool:
    """Whether `after`, whose `json_text` may be given, changes `before`."""
    if before is None or after is None:
        return before is not after
    # Serialized, so that 1, 1.0 and True stay distinct.
    return json_text(before) != (json_text(after) if after_text is None else after_text)


def changed_writes(
    store: Mapping[str, JsonValue], writes: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """The `writes` that change `store`; a commit saves only these."""
    return {
        key: value for key, value in writes.items() if _differs(store.get(key), value)
    }


def store_limit_error(
    *, before: int, after: int, committed: int, stores_values: bool
) -> str | None:
    """Why the store cannot change from `before` to `after` bytes while the
    chat's saved writes and the values that the change stores reach `committed`
    bytes, or None if it can.

    A change that does not grow the store passes the store limit, and writes
    that only delete keys pass the chat limit. Deleted keys do not count toward
    `committed`, so a deletion never makes a later check fail.
    """
    if after > MAX_STORE_BYTES and after > before:
        return (
            f"the store would hold {after} bytes; the limit is {MAX_STORE_BYTES} bytes"
        )
    if stores_values and committed > MAX_COMMITTED_BYTES:
        return (
            f"this chat would save {committed} bytes of store writes; the limit "
            f"is {MAX_COMMITTED_BYTES} bytes per chat"
        )
    return None


def commit_limit_error(
    current: StoreSnapshot, writes: Mapping[str, JsonValue]
) -> str | None:
    """Why `writes` cannot commit onto `current`, or None if they can.

    store() checks the limits against the store a program started with; this
    checks them again against commits that other programs made meanwhile.
    """
    before = sum(entry_bytes(key, value) for key, value in current.values.items())
    after = (
        before
        - sum(
            entry_bytes(key, current.values[key])
            for key in writes
            if key in current.values
        )
        + sum(
            entry_bytes(key, value)
            for key, value in writes.items()
            if value is not None
        )
    )
    error = store_limit_error(
        before=before,
        after=after,
        committed=current.committed_bytes
        + sum(
            entry_bytes(key, value)
            for key, value in writes.items()
            if value is not None
        ),
        stores_values=any(value is not None for value in writes.values()),
    )
    # Each store() call passed, so the cause is what other programs committed.
    return None if error is None else f"other programs committed first, so {error}"


def store_summary(writes: Mapping[str, JsonValue]) -> str | None:
    """One line on a commit's writes, so the model knows the keys."""
    stored = [key for key, value in writes.items() if value is not None]
    deleted = [key for key, value in writes.items() if value is None]
    parts = [
        *([f"Stored: {', '.join(stored)}."] if stored else []),
        *([f"Deleted from the store: {', '.join(deleted)}."] if deleted else []),
    ]
    return " ".join(parts) or None


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
        # Bytes of each changed value that the commit stores, and their sum.
        self._write_sizes: dict[str, int] = {}
        self._write_total = 0

    @property
    def writes(self) -> dict[str, JsonValue]:
        """The last value written to each key, None deleting it; also writes that
        do not change the store."""
        return dict(self._writes)

    @property
    def changed_writes(self) -> dict[str, JsonValue]:
        """The writes that change the store this program started with."""
        return changed_writes(self._snapshot.values, self._writes)

    @property
    def functions(self) -> dict[str, Callable[..., JsonValue]]:
        """store() and load() as the program calls them."""
        return {STORE_FUNCTION: self.store, LOAD_FUNCTION: self.load}

    def load(self, key: object) -> JsonValue:
        return self._values.get(_valid_key(key))

    def store(self, key: object, value: object) -> None:
        valid_key = _valid_key(key)
        copied = json_value(
            value, f'Cannot store "{valid_key}": the value', MAX_STORED_VALUE_BYTES
        )
        stored = copied.value
        size = 0 if stored is None else len(valid_key.encode("utf-8")) + copied.size
        total = self._total - self._sizes.get(valid_key, 0) + size
        write_size = (
            size
            if _differs(self._snapshot.values.get(valid_key), stored, copied.text)
            else 0
        )
        write_total = (
            self._write_total - self._write_sizes.get(valid_key, 0) + write_size
        )
        error = store_limit_error(
            before=self._total,
            after=total,
            committed=self._snapshot.committed_bytes + write_total,
            stores_values=stored is not None,
        )
        if error is not None:
            raise ValueError(
                f'Cannot store "{valid_key}": {error}. Store less, delete keys with '
                "store(key, None), or start a new chat; values stored earlier stay "
                "available with load()."
            )
        self._total = total
        self._write_total = write_total
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
