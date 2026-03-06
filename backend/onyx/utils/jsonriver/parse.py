"""
JSON parser for streaming incremental parsing

Copyright (c) 2023 Google LLC (original TypeScript implementation)
Copyright (c) 2024 jsonriver-python contributors (Python port)
SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import copy
from enum import IntEnum
from typing import cast
from typing import Union

from .tokenize import _Input
from .tokenize import json_token_type_to_string
from .tokenize import JsonTokenType
from .tokenize import Tokenizer


# Type definitions for JSON values
JsonValue = Union[None, bool, float, str, list["JsonValue"], dict[str, "JsonValue"]]
JsonObject = dict[str, JsonValue]


class _StateEnum(IntEnum):
    """Parser state machine states"""

    Initial = 0
    InString = 1
    InArray = 2
    InObjectExpectingKey = 3
    InObjectExpectingValue = 4


class _State:
    """Base class for parser states"""

    type: _StateEnum
    value: JsonValue | tuple[str, JsonObject] | None


class _InitialState(_State):
    """Initial state before any parsing"""

    def __init__(self) -> None:
        self.type = _StateEnum.Initial
        self.value = None


class _InStringState(_State):
    """State while parsing a string"""

    def __init__(self) -> None:
        self.type = _StateEnum.InString
        self.value = ""


class _InArrayState(_State):
    """State while parsing an array"""

    def __init__(self) -> None:
        self.type = _StateEnum.InArray
        self.value: list[JsonValue] = []


class _InObjectExpectingKeyState(_State):
    """State while parsing an object, expecting a key"""

    def __init__(self) -> None:
        self.type = _StateEnum.InObjectExpectingKey
        self.value: JsonObject = {}


class _InObjectExpectingValueState(_State):
    """State while parsing an object, expecting a value"""

    def __init__(self, key: str, obj: JsonObject) -> None:
        self.type = _StateEnum.InObjectExpectingValue
        self.value = (key, obj)


# Sentinel value to distinguish "not set" from "set to None/null"
class _Unset:
    pass


_UNSET = _Unset()


class _Parser:
    """
    Incremental JSON parser

    Feed chunks of JSON text via feed() and get back progressively
    more complete JSON values.
    """

    def __init__(self) -> None:
        self._state_stack: list[_State] = [_InitialState()]
        self._toplevel_value: JsonValue | _Unset = _UNSET
        self._input = _Input()
        self.tokenizer = Tokenizer(self._input, self)
        self._finished = False
        self._progressed = False
        self._prev_snapshot: JsonValue | _Unset = _UNSET

    def feed(self, chunk: str) -> list[JsonValue]:
        """
        Feed a chunk of JSON text and return deltas from the previous state.

        Each element in the returned list represents what changed since the
        last yielded value. For dicts, only changed/new keys are included,
        with string values containing only the newly appended characters.
        """
        if self._finished:
            return []

        self._input.feed(chunk)
        return self._collect_deltas()

    @staticmethod
    def _compute_delta(prev: JsonValue | None, current: JsonValue) -> JsonValue | None:
        if prev is None:
            return current

        if isinstance(current, dict) and isinstance(prev, dict):
            result: JsonObject = {}
            for key in current:
                cur_val = current[key]
                prev_val = prev.get(key)
                if key not in prev:
                    result[key] = cur_val
                elif isinstance(cur_val, str) and isinstance(prev_val, str):
                    if cur_val != prev_val:
                        result[key] = cur_val[len(prev_val) :]
                elif isinstance(cur_val, list) and isinstance(prev_val, list):
                    if cur_val != prev_val:
                        new_items = cur_val[len(prev_val) :]
                        # check if the last existing element was updated
                        if prev_val and cur_val[len(prev_val) - 1] != prev_val[-1]:
                            result[key] = [cur_val[len(prev_val) - 1]] + new_items
                        elif new_items:
                            result[key] = new_items
                elif cur_val != prev_val:
                    result[key] = cur_val
            return result if result else None

        if isinstance(current, str) and isinstance(prev, str):
            delta = current[len(prev) :]
            return delta if delta else None

        if isinstance(current, list) and isinstance(prev, list):
            if current != prev:
                new_items = current[len(prev) :]
                if prev and current[len(prev) - 1] != prev[-1]:
                    return [current[len(prev) - 1]] + new_items
                return new_items if new_items else None
            return None

        if current != prev:
            return current
        return None

    def finish(self) -> list[JsonValue]:
        """Signal that no more chunks will be fed. Validates trailing content.

        Returns any final deltas produced by flushing pending tokens (e.g.
        numbers, which have no terminator and wait for more input).
        """
        self._input.mark_complete()
        # Pump once more so the tokenizer can emit tokens that were waiting
        # for more input (e.g. numbers need buffer_complete to finalize).
        results = self._collect_deltas()
        self._input.expect_end_of_content()
        return results

    def _collect_deltas(self) -> list[JsonValue]:
        """Run one pump cycle and return any deltas produced."""
        results: list[JsonValue] = []
        while True:
            self._progressed = False
            self.tokenizer.pump()

            if self._progressed:
                if self._toplevel_value is _UNSET:
                    raise RuntimeError(
                        "Internal error: toplevel_value should not be unset "
                        "after progressing"
                    )
                current = copy.deepcopy(cast(JsonValue, self._toplevel_value))
                if isinstance(self._prev_snapshot, _Unset):
                    results.append(current)
                else:
                    delta = self._compute_delta(self._prev_snapshot, current)
                    if delta is not None:
                        results.append(delta)
                self._prev_snapshot = current
            else:
                if not self._state_stack:
                    self._finished = True
                break
        return results

    # TokenHandler protocol implementation

    def handle_null(self) -> None:
        """Handle null token"""
        self._handle_value_token(JsonTokenType.Null, None)

    def handle_boolean(self, value: bool) -> None:
        """Handle boolean token"""
        self._handle_value_token(JsonTokenType.Boolean, value)

    def handle_number(self, value: float) -> None:
        """Handle number token"""
        self._handle_value_token(JsonTokenType.Number, value)

    def handle_string_start(self) -> None:
        """Handle string start token"""
        state = self._current_state()
        if not self._progressed and state.type != _StateEnum.InObjectExpectingKey:
            self._progressed = True

        if state.type == _StateEnum.Initial:
            self._state_stack.pop()
            self._toplevel_value = self._progress_value(JsonTokenType.StringStart, None)

        elif state.type == _StateEnum.InArray:
            v = self._progress_value(JsonTokenType.StringStart, None)
            arr = cast(list[JsonValue], state.value)
            arr.append(v)

        elif state.type == _StateEnum.InObjectExpectingKey:
            self._state_stack.append(_InStringState())

        elif state.type == _StateEnum.InObjectExpectingValue:
            key, obj = cast(tuple[str, JsonObject], state.value)
            sv = self._progress_value(JsonTokenType.StringStart, None)
            obj[key] = sv

        elif state.type == _StateEnum.InString:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(JsonTokenType.StringStart)} "
                f"token in the middle of string"
            )

    def handle_string_middle(self, value: str) -> None:
        """Handle string middle token"""
        state = self._current_state()

        if not self._progressed:
            if len(self._state_stack) >= 2:
                prev = self._state_stack[-2]
                if prev.type != _StateEnum.InObjectExpectingKey:
                    self._progressed = True
            else:
                self._progressed = True

        if state.type != _StateEnum.InString:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(JsonTokenType.StringMiddle)} "
                f"token when not in string"
            )

        assert isinstance(state.value, str)
        state.value += value

        parent_state = self._state_stack[-2] if len(self._state_stack) >= 2 else None
        self._update_string_parent(state.value, parent_state)

    def handle_string_end(self) -> None:
        """Handle string end token"""
        state = self._current_state()

        if state.type != _StateEnum.InString:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(JsonTokenType.StringEnd)} "
                f"token when not in string"
            )

        self._state_stack.pop()
        parent_state = self._state_stack[-1] if self._state_stack else None
        assert isinstance(state.value, str)
        self._update_string_parent(state.value, parent_state)

    def handle_array_start(self) -> None:
        """Handle array start token"""
        self._handle_value_token(JsonTokenType.ArrayStart, None)

    def handle_array_end(self) -> None:
        """Handle array end token"""
        state = self._current_state()
        if state.type != _StateEnum.InArray:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(JsonTokenType.ArrayEnd)} token"
            )
        self._state_stack.pop()

    def handle_object_start(self) -> None:
        """Handle object start token"""
        self._handle_value_token(JsonTokenType.ObjectStart, None)

    def handle_object_end(self) -> None:
        """Handle object end token"""
        state = self._current_state()

        if state.type in (
            _StateEnum.InObjectExpectingKey,
            _StateEnum.InObjectExpectingValue,
        ):
            self._state_stack.pop()
        else:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(JsonTokenType.ObjectEnd)} token"
            )

    # Private helper methods

    def _current_state(self) -> _State:
        """Get current parser state"""
        if not self._state_stack:
            raise ValueError("Unexpected trailing input")
        return self._state_stack[-1]

    def _handle_value_token(self, token_type: JsonTokenType, value: JsonValue) -> None:
        """Handle a complete value token"""
        state = self._current_state()

        if not self._progressed:
            self._progressed = True

        if state.type == _StateEnum.Initial:
            self._state_stack.pop()
            self._toplevel_value = self._progress_value(token_type, value)

        elif state.type == _StateEnum.InArray:
            v = self._progress_value(token_type, value)
            arr = cast(list[JsonValue], state.value)
            arr.append(v)

        elif state.type == _StateEnum.InObjectExpectingValue:
            key, obj = cast(tuple[str, JsonObject], state.value)
            if token_type != JsonTokenType.StringStart:
                self._state_stack.pop()
                new_state = _InObjectExpectingKeyState()
                new_state.value = obj
                self._state_stack.append(new_state)

            v = self._progress_value(token_type, value)
            obj[key] = v

        elif state.type == _StateEnum.InString:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(token_type)} "
                f"token in the middle of string"
            )

        elif state.type == _StateEnum.InObjectExpectingKey:
            raise ValueError(
                f"Unexpected {json_token_type_to_string(token_type)} "
                f"token in the middle of object expecting key"
            )

    def _update_string_parent(self, updated: str, parent_state: _State | None) -> None:
        """Update parent container with updated string value"""
        if parent_state is None:
            self._toplevel_value = updated

        elif parent_state.type == _StateEnum.InArray:
            arr = cast(list[JsonValue], parent_state.value)
            arr[-1] = updated

        elif parent_state.type == _StateEnum.InObjectExpectingValue:
            key, obj = cast(tuple[str, JsonObject], parent_state.value)
            obj[key] = updated
            if self._state_stack and self._state_stack[-1] == parent_state:
                self._state_stack.pop()
                new_state = _InObjectExpectingKeyState()
                new_state.value = obj
                self._state_stack.append(new_state)

        elif parent_state.type == _StateEnum.InObjectExpectingKey:
            if self._state_stack and self._state_stack[-1] == parent_state:
                self._state_stack.pop()
                obj = cast(JsonObject, parent_state.value)
                self._state_stack.append(_InObjectExpectingValueState(updated, obj))

    def _progress_value(self, token_type: JsonTokenType, value: JsonValue) -> JsonValue:
        """Create initial value for a token and push appropriate state"""
        if token_type == JsonTokenType.Null:
            return None

        elif token_type == JsonTokenType.Boolean:
            return value

        elif token_type == JsonTokenType.Number:
            return value

        elif token_type == JsonTokenType.StringStart:
            string_state = _InStringState()
            self._state_stack.append(string_state)
            return ""

        elif token_type == JsonTokenType.ArrayStart:
            array_state = _InArrayState()
            self._state_stack.append(array_state)
            return array_state.value

        elif token_type == JsonTokenType.ObjectStart:
            object_state = _InObjectExpectingKeyState()
            self._state_stack.append(object_state)
            return object_state.value

        else:
            raise ValueError(
                f"Unexpected token type: {json_token_type_to_string(token_type)}"
            )
