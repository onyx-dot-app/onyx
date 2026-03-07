"""
JSON tokenizer for streaming incremental parsing

Copyright (c) 2023 Google LLC (original TypeScript implementation)
Copyright (c) 2024 jsonriver-python contributors (Python port)
SPDX-License-Identifier: BSD-3-Clause
"""

from __future__ import annotations

import re
from enum import IntEnum
from typing import Protocol


class TokenHandler(Protocol):
    """Protocol for handling JSON tokens"""

    def handle_null(self) -> None: ...
    def handle_boolean(self, value: bool) -> None: ...
    def handle_number(self, value: float) -> None: ...
    def handle_string_start(self) -> None: ...
    def handle_string_middle(self, value: str) -> None: ...
    def handle_string_end(self) -> None: ...
    def handle_array_start(self) -> None: ...
    def handle_array_end(self) -> None: ...
    def handle_object_start(self) -> None: ...
    def handle_object_end(self) -> None: ...


class JsonTokenType(IntEnum):
    """Types of JSON tokens"""

    Null = 0
    Boolean = 1
    Number = 2
    StringStart = 3
    StringMiddle = 4
    StringEnd = 5
    ArrayStart = 6
    ArrayEnd = 7
    ObjectStart = 8
    ObjectEnd = 9


def json_token_type_to_string(token_type: JsonTokenType) -> str:
    """Convert token type to readable string"""
    names = {
        JsonTokenType.Null: "null",
        JsonTokenType.Boolean: "boolean",
        JsonTokenType.Number: "number",
        JsonTokenType.StringStart: "string start",
        JsonTokenType.StringMiddle: "string middle",
        JsonTokenType.StringEnd: "string end",
        JsonTokenType.ArrayStart: "array start",
        JsonTokenType.ArrayEnd: "array end",
        JsonTokenType.ObjectStart: "object start",
        JsonTokenType.ObjectEnd: "object end",
    }
    return names[token_type]


class _State(IntEnum):
    """Internal tokenizer states"""

    ExpectingValue = 0
    InString = 1
    StartArray = 2
    AfterArrayValue = 3
    StartObject = 4
    AfterObjectKey = 5
    AfterObjectValue = 6
    BeforeObjectKey = 7


# Regex for validating JSON numbers
_JSON_NUMBER_PATTERN = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$")


def _parse_json_number(s: str) -> float:
    """Parse a JSON number string, validating format"""
    if not _JSON_NUMBER_PATTERN.match(s):
        raise ValueError("Invalid number")
    return float(s)


class _Input:
    """
    Input buffer for chunk-based JSON parsing

    Manages buffering of input chunks and provides methods for
    consuming and inspecting the buffer.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._start_index = 0
        self.buffer_complete = False

    def feed(self, chunk: str) -> None:
        """Add a chunk of data to the buffer"""
        self._buffer += chunk

    def mark_complete(self) -> None:
        """Signal that no more chunks will be fed"""
        self.buffer_complete = True

    @property
    def length(self) -> int:
        """Number of characters remaining in buffer"""
        return len(self._buffer) - self._start_index

    def advance(self, length: int) -> None:
        """Advance the start position by length characters"""
        self._start_index += length

    def peek(self, offset: int) -> str | None:
        """Peek at character at offset, or None if not available"""
        idx = self._start_index + offset
        if idx < len(self._buffer):
            return self._buffer[idx]
        return None

    def peek_char_code(self, offset: int) -> int:
        """Get character code at offset"""
        return ord(self._buffer[self._start_index + offset])

    def slice(self, start: int, end: int) -> str:
        """Slice buffer from start to end (relative to current position)"""
        return self._buffer[self._start_index + start : self._start_index + end]

    def commit(self) -> None:
        """Commit consumed content, removing it from buffer"""
        if self._start_index > 0:
            self._buffer = self._buffer[self._start_index :]
            self._start_index = 0

    def remaining(self) -> str:
        """Get all remaining content in buffer"""
        return self._buffer[self._start_index :]

    def expect_end_of_content(self) -> None:
        """Verify no non-whitespace content remains"""
        self.commit()
        self.skip_past_whitespace()
        if self.length != 0:
            raise ValueError(f"Unexpected trailing content {self.remaining()!r}")

    def skip_past_whitespace(self) -> None:
        """Skip whitespace characters"""
        i = self._start_index
        while i < len(self._buffer):
            c = ord(self._buffer[i])
            if c in (32, 9, 10, 13):  # space, tab, \n, \r
                i += 1
            else:
                break
        self._start_index = i

    def try_to_take_prefix(self, prefix: str) -> bool:
        """Try to consume prefix from buffer, return True if successful"""
        if self._buffer.startswith(prefix, self._start_index):
            self._start_index += len(prefix)
            return True
        return False

    def try_to_take(self, length: int) -> str | None:
        """Try to take length characters, or None if not enough available"""
        if self.length < length:
            return None
        result = self._buffer[self._start_index : self._start_index + length]
        self._start_index += length
        return result

    def try_to_take_char_code(self) -> int | None:
        """Try to take a single character as char code, or None if buffer empty"""
        if self.length == 0:
            return None
        code = ord(self._buffer[self._start_index])
        self._start_index += 1
        return code

    def take_until_quote_or_backslash(self) -> tuple[str, bool]:
        """
        Consume input up to first quote or backslash

        Returns tuple of (consumed_content, pattern_found)
        """
        buf = self._buffer
        i = self._start_index
        while i < len(buf):
            c = ord(buf[i])
            if c <= 0x1F:
                raise ValueError("Unescaped control character in string")
            if c == 34 or c == 92:  # " or \
                result = buf[self._start_index : i]
                self._start_index = i
                return (result, True)
            i += 1

        result = buf[self._start_index :]
        self._start_index = len(buf)
        return (result, False)


class Tokenizer:
    """
    Tokenizer for chunk-based JSON parsing

    Processes chunks fed into its input buffer and calls handler methods
    as JSON tokens are recognized.
    """

    def __init__(self, input: _Input, handler: TokenHandler) -> None:
        self.input = input
        self._handler = handler
        self._stack: list[_State] = [_State.ExpectingValue]
        self._emitted_tokens = 0

    def is_done(self) -> bool:
        """Check if tokenization is complete"""
        return len(self._stack) == 0 and self.input.length == 0

    def pump(self) -> None:
        """Process all available tokens in the buffer"""
        while True:
            before = self._emitted_tokens
            self._tokenize_more()
            if self._emitted_tokens == before:
                self.input.commit()
                return

    def _tokenize_more(self) -> None:
        """Process one step of tokenization based on current state"""
        if not self._stack:
            return

        state = self._stack[-1]

        if state == _State.ExpectingValue:
            self._tokenize_value()
        elif state == _State.InString:
            self._tokenize_string()
        elif state == _State.StartArray:
            self._tokenize_array_start()
        elif state == _State.AfterArrayValue:
            self._tokenize_after_array_value()
        elif state == _State.StartObject:
            self._tokenize_object_start()
        elif state == _State.AfterObjectKey:
            self._tokenize_after_object_key()
        elif state == _State.AfterObjectValue:
            self._tokenize_after_object_value()
        elif state == _State.BeforeObjectKey:
            self._tokenize_before_object_key()

    def _tokenize_value(self) -> None:
        """Tokenize a JSON value"""
        self.input.skip_past_whitespace()

        if self.input.try_to_take_prefix("null"):
            self._handler.handle_null()
            self._emitted_tokens += 1
            self._stack.pop()
            return

        if self.input.try_to_take_prefix("true"):
            self._handler.handle_boolean(True)
            self._emitted_tokens += 1
            self._stack.pop()
            return

        if self.input.try_to_take_prefix("false"):
            self._handler.handle_boolean(False)
            self._emitted_tokens += 1
            self._stack.pop()
            return

        if self.input.length > 0:
            ch = self.input.peek_char_code(0)
            if (48 <= ch <= 57) or ch == 45:  # 0-9 or -
                # Scan for end of number
                i = 0
                while i < self.input.length:
                    c = self.input.peek_char_code(i)
                    if (48 <= c <= 57) or c in (45, 43, 46, 101, 69):  # 0-9 - + . e E
                        i += 1
                    else:
                        break

                if i == self.input.length and not self.input.buffer_complete:
                    # Need more input (numbers have no terminator)
                    return

                number_chars = self.input.slice(0, i)
                self.input.advance(i)
                number = _parse_json_number(number_chars)
                self._handler.handle_number(number)
                self._emitted_tokens += 1
                self._stack.pop()
                return

        if self.input.try_to_take_prefix('"'):
            self._stack.pop()
            self._stack.append(_State.InString)
            self._handler.handle_string_start()
            self._emitted_tokens += 1
            self._tokenize_string()
            return

        if self.input.try_to_take_prefix("["):
            self._stack.pop()
            self._stack.append(_State.StartArray)
            self._handler.handle_array_start()
            self._emitted_tokens += 1
            self._tokenize_array_start()
            return

        if self.input.try_to_take_prefix("{"):
            self._stack.pop()
            self._stack.append(_State.StartObject)
            self._handler.handle_object_start()
            self._emitted_tokens += 1
            self._tokenize_object_start()
            return

    def _tokenize_string(self) -> None:
        """Tokenize string content"""
        while True:
            chunk, interrupted = self.input.take_until_quote_or_backslash()
            if chunk:
                self._handler.handle_string_middle(chunk)
                self._emitted_tokens += 1
            elif not interrupted:
                return

            if interrupted:
                if self.input.length == 0:
                    return

                next_char = self.input.peek(0)
                if next_char == '"':
                    self.input.advance(1)
                    self._handler.handle_string_end()
                    self._emitted_tokens += 1
                    self._stack.pop()
                    return

                # Handle escape sequences
                next_char2 = self.input.peek(1)
                if next_char2 is None:
                    return

                value: str
                if next_char2 == "u":
                    # Unicode escape: need 4 hex digits
                    if self.input.length < 6:
                        return

                    code = 0
                    for j in range(2, 6):
                        c = self.input.peek_char_code(j)
                        if 48 <= c <= 57:  # 0-9
                            digit = c - 48
                        elif 65 <= c <= 70:  # A-F
                            digit = c - 55
                        elif 97 <= c <= 102:  # a-f
                            digit = c - 87
                        else:
                            raise ValueError("Bad Unicode escape in JSON")
                        code = (code << 4) | digit

                    self.input.advance(6)
                    self._handler.handle_string_middle(chr(code))
                    self._emitted_tokens += 1
                    continue

                elif next_char2 == "n":
                    value = "\n"
                elif next_char2 == "r":
                    value = "\r"
                elif next_char2 == "t":
                    value = "\t"
                elif next_char2 == "b":
                    value = "\b"
                elif next_char2 == "f":
                    value = "\f"
                elif next_char2 == "\\":
                    value = "\\"
                elif next_char2 == "/":
                    value = "/"
                elif next_char2 == '"':
                    value = '"'
                else:
                    raise ValueError("Bad escape in string")

                self.input.advance(2)
                self._handler.handle_string_middle(value)
                self._emitted_tokens += 1

    def _tokenize_array_start(self) -> None:
        """Tokenize start of array (check for empty or first element)"""
        self.input.skip_past_whitespace()
        if self.input.length == 0:
            return

        if self.input.try_to_take_prefix("]"):
            self._handler.handle_array_end()
            self._emitted_tokens += 1
            self._stack.pop()
            return

        self._stack.pop()
        self._stack.append(_State.AfterArrayValue)
        self._stack.append(_State.ExpectingValue)
        self._tokenize_value()

    def _tokenize_after_array_value(self) -> None:
        """Tokenize after an array value (expect , or ])"""
        self.input.skip_past_whitespace()
        next_char = self.input.try_to_take_char_code()

        if next_char is None:
            return
        elif next_char == 0x5D:  # ]
            self._handler.handle_array_end()
            self._emitted_tokens += 1
            self._stack.pop()
            return
        elif next_char == 0x2C:  # ,
            self._stack.append(_State.ExpectingValue)
            self._tokenize_value()
            return
        else:
            raise ValueError(f"Expected , or ], got {chr(next_char)!r}")

    def _tokenize_object_start(self) -> None:
        """Tokenize start of object (check for empty or first key)"""
        self.input.skip_past_whitespace()
        next_char = self.input.try_to_take_char_code()

        if next_char is None:
            return
        elif next_char == 0x7D:  # }
            self._handler.handle_object_end()
            self._emitted_tokens += 1
            self._stack.pop()
            return
        elif next_char == 0x22:  # "
            self._stack.pop()
            self._stack.append(_State.AfterObjectKey)
            self._stack.append(_State.InString)
            self._handler.handle_string_start()
            self._emitted_tokens += 1
            self._tokenize_string()
            return
        else:
            raise ValueError(f"Expected start of object key, got {chr(next_char)!r}")

    def _tokenize_after_object_key(self) -> None:
        """Tokenize after object key (expect :)"""
        self.input.skip_past_whitespace()
        next_char = self.input.try_to_take_char_code()

        if next_char is None:
            return
        elif next_char == 0x3A:  # :
            self._stack.pop()
            self._stack.append(_State.AfterObjectValue)
            self._stack.append(_State.ExpectingValue)
            self._tokenize_value()
            return
        else:
            raise ValueError(f"Expected colon after object key, got {chr(next_char)!r}")

    def _tokenize_after_object_value(self) -> None:
        """Tokenize after object value (expect , or })"""
        self.input.skip_past_whitespace()
        next_char = self.input.try_to_take_char_code()

        if next_char is None:
            return
        elif next_char == 0x7D:  # }
            self._handler.handle_object_end()
            self._emitted_tokens += 1
            self._stack.pop()
            return
        elif next_char == 0x2C:  # ,
            self._stack.pop()
            self._stack.append(_State.BeforeObjectKey)
            self._tokenize_before_object_key()
            return
        else:
            raise ValueError(
                f"Expected , or }} after object value, got {chr(next_char)!r}"
            )

    def _tokenize_before_object_key(self) -> None:
        """Tokenize before object key (after comma)"""
        self.input.skip_past_whitespace()
        next_char = self.input.try_to_take_char_code()

        if next_char is None:
            return
        elif next_char == 0x22:  # "
            self._stack.pop()
            self._stack.append(_State.AfterObjectKey)
            self._stack.append(_State.InString)
            self._handler.handle_string_start()
            self._emitted_tokens += 1
            self._tokenize_string()
            return
        else:
            raise ValueError(f"Expected start of object key, got {chr(next_char)!r}")
